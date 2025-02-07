1. `sudo apt install libportaudio2 python3-gi python3-gi-cairo gir1.2-gtk-3.0 libgirepository1.0-dev libcairo2-dev libdbus-1-dev libnotify-bin`
2. Скачать бинари ydotool c https://github.com/ReimuNotMoe/ydotool/releases/latest (в репозитории для Убунту очень старая версия, она не работает)
3. `python -m venv venv`
4. `source venv/bin/activate`
5. `pip install -r requirements.txt`
6. `pip install torch --index-url https://download.pytorch.org/whl/rocm6.2` - это ставим отдельно, т.к. надо поставить именно ту версию, которая поддерживает мою видюху. В моем случае это прослойка ROCm версии 6.2 для видюх AMD.
7. Надо создать сервис DBus, чтобы была возможность прослушивать сигнал от хоткея. Создайте файл `/usr/share/dbus-1/services/org.voice.input.service` с таким содержимым:
  ```
  [D-BUS Service]
  Name=viktorprogger.home.s2t
  Exec=/путь/к/вашему/venv/bin/python3 /путь/к/main.py
  ```
7. В настройках Убунту добавить хоткей для команды `dbus-send --session --type=signal /org/voice/input viktorprogger.home.s2t.ToggleRecording`. Я поставил на Ctrl + Shift + X.
8. Запустить `ydotoold` и `main.py`. Важно делать это от имени своего юзера и в графическом интерфейсе. Все попытки посадить эти команды на автостарт у меня провалились, поэтому я написал себе такую вот функцию для баша:
  ```bash
  s2t() {
    nohup ydotoold &
    nohup /home/viktor/projects/viktorprogger/speech-to-text/venv/bin/python3 /home/viktor/projects/viktorprogger/speech-to-text/main.py &
  }
  ```
  И теперь пишу в терминале `s2t`, чтобы запустить свой speech to text сервис.
