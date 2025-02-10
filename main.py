import gi
from dbus import service

gi.require_version("Gtk", "3.0")
import os
import shlex
import queue
import subprocess
import threading
import time

import dbus
import numpy as np
import sounddevice as sd
import whisper
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import Gtk

LANGUAGE_CONSTANT = "en"


class VoiceInputSystem:
    def __init__(self):
        # self.setup_tray()
        os.environ["HSA_OVERRIDE_GFX_VERSION"] = "11.0.0"

        self.model = whisper.load_model(
            "medium",
            device="cuda",
        )
        # Прогрев модели пустым аудиосигналом
        self.model.transcribe(
            np.zeros((16000,), dtype=np.float32), language=LANGUAGE_CONSTANT
        )
        self.recording = False
        self.audio_queue = queue.Queue()
        self.text_queue = queue.Queue()
        self.previous_phrase = None

        self.audio_buffer = []
        self.silence_start = None  # Время начала тишины
        self.silence_threshold = 0.01  # Порог тишины (можно менять)
        self.silence_duration = 1.0  # Минимальная длительность паузы (в секундах)

        self.audio_thread = None  # Поток обработки аудио
        self.stop_event = threading.Event()  # Флаг ожидания сигнала D-Bus
        self.input_stream = None  # Поток записи микрофона

        # Настраиваем D-Bus для приема сигналов от системных хоткеев
        self.setup_dbus()
        # self.indicator.set_icon("microphone")
        # self.indicator.set_title("Voice Input (Inactive)")

    # def setup_tray(self):
    #     # Создаем индикатор приложения
    #     self.indicator = AppIndicator3.Indicator.new(
    #         "viktorprogger-speech-to-text",  # Уникальный идентификатор
    #         "loading",  # Имя иконки или путь к файлу
    #         AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
    #     )
    #     self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)

    #     # Создаем меню для правой кнопки
    #     self.menu = Gtk.Menu()

    #     # Пункт меню "Quit"
    #     quit_item = Gtk.MenuItem(label="Quit")
    #     quit_item.connect("activate", self.on_quit)
    #     self.menu.append(quit_item)

    #     self.menu.show_all()
    #     self.indicator.set_menu(self.menu)

    # def on_quit(self):
    #     Gtk.main_quit()

    def setup_dbus(self):
        DBusGMainLoop(set_as_default=True)
        bus = dbus.SessionBus()

        # Регистрируем сервис для приема сигналов
        bus_name = service.BusName("viktorprogger.home.s2t", bus)

        # Слушаем сигналы от системы
        bus.add_signal_receiver(
            self.toggle_recording,
            dbus_interface="viktorprogger.home.s2t",
            signal_name="ToggleRecording",
        )

    def show_notification(self, message):
        subprocess.run(
            [
                "notify-send",
                "-h",
                "string:x-canonical-private-synchronous:speech-to-text",
                "-h",
                "int:transient:1",
                "Voice Input",
                message,
            ],
            check=True,
        )

    # def on_right_click(self, icon, button, time):
    #     menu = Gtk.Menu()

    #     quit_item = Gtk.MenuItem(label="Quit")
    #     quit_item.connect("activate", self.quit)
    #     menu.append(quit_item)

    #     menu.show_all()
    #     menu.popup(None, None, None, None, button, time)

    def quit(self, _):
        Gtk.main_quit()
        os._exit(0)

    def audio_callback(self, indata, frames, timeinfo, status):
        if self.recording:
            volume = np.max(np.abs(indata))  # Определяем громкость

            if volume > self.silence_threshold:
                self.audio_buffer.append(indata.copy())  # Запоминаем звук
                self.silence_start = None  # Сбрасываем таймер тишины
            else:
                if self.silence_start is None:
                    self.silence_start = time.time()  # Запоминаем время начала тишины

    def process_audio(self):
        while self.stop_event.is_set():
            silence_start = self.silence_start
            if (
                silence_start is not None
                and (time.time() - silence_start) > self.silence_duration
            ):
                self.silence_start = None  # Сбрасываем таймер тишины
                if self.audio_buffer:
                    # Собираем звук в единый массив
                    audio = (
                        np.concatenate(self.audio_buffer).flatten().astype(np.float32)
                    )
                    self.audio_buffer = []  # Очищаем буфер после обработки

                    # Отправляем в Whisper
                    # Add previous phrase as context if available
                    initial_prompt = (
                        self.previous_phrase if self.previous_phrase else None
                    )
                    result = self.model.transcribe(
                        audio, language=LANGUAGE_CONSTANT, initial_prompt=initial_prompt
                    )
                    text = result["text"]

                    if text.strip() and result["segments"]:
                        if (
                            result["segments"][0]["avg_logprob"] > -1.5
                            and result["segments"][0]["no_speech_prob"] < 0.5
                        ):
                            self.text_queue.put(text)  # Отправляем текст в очередь
                            self.previous_phrase = (
                                text  # Сохраняем фразу для следующего контекста
                            )
                        else:
                            print(
                                "Text not sent to queue. logprob: {}, no_speech_prob: {}".format(
                                    result["segments"][0]["avg_logprob"],
                                    result["segments"][0]["no_speech_prob"],
                                )
                            )
                            print(text)

                time.sleep(0.5)  # Небольшая пауза в цикле

    def type_text(self):
        while True:
            if not self.text_queue.empty():
                text = self.text_queue.get()
                try:
                    # Вводим текст
                    subprocess.run(
                        f"echo -n {shlex.quote(text)} | wl-copy && sleep 0.1 && /home/viktor/.local/bin/ydotool key 29:1 47:1 47:0 29:0",
                        shell=True,
                        check=True,
                    )

                except subprocess.CalledProcessError as e:
                    print(f"Error typing text: {e}")
            time.sleep(0.1)

    def toggle_recording(self):
        self.recording = not self.recording

        if self.recording:
            self.show_notification("Voice input activated")
            self.stop_event.set()  # Разрешаем выполнение потоков

            # Запуск обработки аудио
            if self.audio_thread is None or not self.audio_thread.is_alive():
                self.audio_thread = threading.Thread(target=self.process_audio)
                self.audio_thread.daemon = True
                self.audio_thread.start()

            # Запуск микрофона
            if self.input_stream is None:
                self.input_stream = sd.InputStream(
                    callback=self.audio_callback, channels=1, samplerate=16000
                )
                self.input_stream.start()
        else:
            self.show_notification("Voice input deactivated")
            self.stop_event.clear()  # Останавливаем обработку
            self.previous_phrase = None  # Сбрасываем предыдущую фразу
            if self.input_stream:
                self.input_stream.stop()
                self.input_stream.close()
                self.input_stream = None

    def run(self):
        # Запускаем потоки обработки
        audio_thread = threading.Thread(target=self.process_audio)
        audio_thread.daemon = True
        audio_thread.start()

        text_thread = threading.Thread(target=self.type_text)
        text_thread.daemon = True
        text_thread.start()

        # Запускаем запись звука
        with sd.InputStream(callback=self.audio_callback, channels=1, samplerate=16000):
            # Запускаем главный цикл GTK
            Gtk.main()


if __name__ == "__main__":
    vis = VoiceInputSystem()
    vis.run()
