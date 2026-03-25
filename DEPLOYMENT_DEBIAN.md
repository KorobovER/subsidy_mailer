# Развертывание на Debian 9

## Параметры сервера
- **OS**: Debian 9
- **IP**: 10.10.20.250/24
- **Назначение**: Формирование и отправка реестров платежей
- **Ответственный**: Департамент дорож хоз (Брюханцев)

## Шаги установки

### 1. Подключение к серверу
```bash
ssh user@10.10.20.250
```

### 2. Установка Python и зависимостей
```bash
sudo apt-get update
sudo apt-get install -y python3 python3-pip
```

### 3. Создание директории для скрипта
```bash
sudo mkdir -p /opt/subsidy_mailer
cd /opt/subsidy_mailer
```

**Примечание:** Если вы работаете под рутом, команда `sudo chown` не требуется.

### 4. Копирование файлов со своего ПК
```bash
# На вашем ПК (Windows):
scp subsidy_mailer.py user@10.10.20.250:/opt/subsidy_mailer/
scp config-prod.json user@10.10.20.250:/opt/subsidy_mailer/
```

Или скопировать вручную через SFTP.

### 5. Создание необходимых папок
```bash
cd /opt/subsidy_mailer
mkdir -p logs archives
```

### 6. Проверка конфига
```bash
# Отредактировать config-prod.json с правильными путями
nano config-prod.json
```

**Важно**: `source_dir` должен указывать на папку на старом сервере:
```json
"source_dir": "/mnt/old_server",
"archive_dir": "/mnt/old_server/Архив"
```

### 7. Первый тест
```bash
python3 subsidy_mailer.py config-prod.json
```

### 8. Настройка Cron для автоматического запуска

Отредактировать crontab:
```bash
crontab -e
```

Добавить две строки (запуск в 08:00 утром и в 18:00 вечером):
```
0 8 * * * cd /opt/subsidy_mailer && python3 subsidy_mailer.py config-prod.json >> /opt/subsidy_mailer/cron.log 2>&1
0 18 * * * cd /opt/subsidy_mailer && python3 subsidy_mailer.py config-prod.json >> /opt/subsidy_mailer/cron.log 2>&1
```

**Объяснение:**
- `0 8` - в 08:00 (8 часов утра)
- `0 18` - в 18:00 (6 часов вечера)
- `* * *` - каждый день недели и месяца
- `>> /opt/subsidy_mailer/cron.log 2>&1` - логирование вывода
- `config-prod.json` - production конфиг с реальными параметрами

**Другие варианты времени:**
```
# 07:00 и 17:00
0 7 * * * cd /opt/subsidy_mailer && python3 subsidy_mailer.py config-prod.json >> /opt/subsidy_mailer/cron.log 2>&1
0 17 * * * cd /opt/subsidy_mailer && python3 subsidy_mailer.py config-prod.json >> /opt/subsidy_mailer/cron.log 2>&1

# 09:00 и 19:00
0 9 * * * cd /opt/subsidy_mailer && python3 subsidy_mailer.py config-prod.json >> /opt/subsidy_mailer/cron.log 2>&1
0 19 * * * cd /opt/subsidy_mailer && python3 subsidy_mailer.py config-prod.json >> /opt/subsidy_mailer/cron.log 2>&1

# 06:00 и 20:00
0 6 * * * cd /opt/subsidy_mailer && python3 subsidy_mailer.py config-prod.json >> /opt/subsidy_mailer/cron.log 2>&1
0 20 * * * cd /opt/subsidy_mailer && python3 subsidy_mailer.py config-prod.json >> /opt/subsidy_mailer/cron.log 2>&1
```

**Проверка установленных задач:**
```bash
crontab -l
```

### 9. Проверка логов
```bash
tail -f /opt/subsidy_mailer/logs/subsidy_mailer.log
tail -f /opt/subsidy_mailer/cron.log
```

## Доступ к папке на старом сервере

### Подключение к Windows Server 2003 (10.10.30.62)

**Параметры подключения:**
- **IP**: 10.10.30.62
- **Путь на сервере**: `C:\base\CES\!Выгрузка\Субсидии`
- **Логин**: администратор
- **Пароль**: qqq

### Установка и монтирование Samba

```bash
# Установка необходимых пакетов
sudo apt-get install -y cifs-utils

# Создание точки монтирования
sudo mkdir -p /mnt/old_server

# Монтирование сетевой папки
sudo mount -t cifs //10.10.30.62/base/CES/\!Выгрузка/Субсидии \
  -o username=администратор,password=qqq,iocharset=utf8 \
  /mnt/old_server

# Проверка монтирования
ls -la /mnt/old_server/
```

### Постоянное монтирование (при перезагрузке)

Отредактировать `/etc/fstab`:
```bash
sudo nano /etc/fstab
```

Добавить строку:
```
//10.10.30.62/base/CES/\!Выгрузка/Субсидии /mnt/old_server cifs username=администратор,password=qqq,iocharset=utf8,uid=1000,gid=1000 0 0
```

Сохранить (Ctrl+O, Enter, Ctrl+X)

Проверить:
```bash
sudo mount -a
ls -la /mnt/old_server/
```

### Конфигурация скрипта

В файле `/opt/subsidy_mailer/config.json` установить:

```json
{
  "source_dir": "/mnt/old_server",
  "archive_dir": "/mnt/old_server/Архив",
  ...
}
```

**Объяснение:**
- `source_dir`: `/mnt/old_server` - папка с файлами для отправки
- `archive_dir`: `/mnt/old_server/Архив` - папка для сохранения архивов

## Проверка работы

```bash
# Проверить доступ к папке
ls -la /mnt/old_server/

# Запустить скрипт вручную
python3 /opt/subsidy_mailer/subsidy_mailer.py /opt/subsidy_mailer/config.json

# Проверить логи
cat /opt/subsidy_mailer/logs/subsidy_mailer.log
```

## Решение проблем

**Ошибка: "Connection unexpectedly closed"**
- Проверить доступность SMTP сервера
- Проверить firewall правила

**Ошибка: "Permission denied"**
- Проверить права доступа к папкам
- `chmod 755 /opt/subsidy_mailer`

**Ошибка: "No such file or directory"**
- Проверить путь к `source_dir`
- Проверить монтирование сетевой папки

## Резервная копия конфига
```bash
# Сохранить config.json в безопасное место
sudo cp config.json config.json.backup
```
