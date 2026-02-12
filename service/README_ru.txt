Кратко, что сделано:
1. Реестр в виде текста для письма
В pdf_io.py добавлена функция format_payment_register_text(payments) — возвращает текстовый реестр платежей (таблица с колонками и итогом) для тела письма.
2. Сервис в service/mail_service.py
IMAP: подключение по SSL (порт 993), выбор ящика, поиск писем с флагом UNSEEN.
Вложения: обход MIME, отбор частей с attachment и именем файла, оканчивающимся на .pdf.
Обработка: каждый PDF сохраняется во временный файл, вызывается process_pdf(); при успехе во вложения ответа добавляются оригинал и файл {name}_epc_qr.pdf.
Тело письма: текст реестра по каждому обработанному PDF (или строка «No UNP QR codes found...», если UNP не найдены).
Ответ: тема RE: + исходная тема, получатель — адрес из From, отправка через SMTP (STARTTLS при необходимости).
Удаление: после успешной отправки письмо помечается \Deleted, в конце цикла вызывается expunge.
3. Переменные окружения
Описаны в service/README.md: IMAP_* (HOST, PORT, USER, PASSWORD, MAILBOX), SMTP_* (HOST, PORT, USER, PASSWORD, USE_TLS), FROM_EMAIL, POLL_INTERVAL.
4. Docker
service/Dockerfile: образ на python:3.12-slim, установка libgl1-mesa-glx и libglib2.0-0 для OpenCV, копирование кода и requirements.txt, запуск python mail_service.py.
Сборка из корня репозитория:
docker build -f service/Dockerfile -t unp-epc-qr-mail .
Запуск контейнера (пример):
cd /Users/denis.chertkov/work/unp-to-epc-qrdocker build -f service/Dockerfile -t unp-epc-qr-mail .docker run --rm --env-file .env unp-epc-qr-mail
Файл .env в корне репозитория с переменными IMAP_* и SMTP_* (см. пример в service/README.md).
