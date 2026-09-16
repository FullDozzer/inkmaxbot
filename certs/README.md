# Корневые сертификаты для TLS

`max_ca_bundle.crt` содержит два сертификата УЦ Минцифры России
(Russian Trusted CA): корневой и выпускающий.

**Зачем они нужны.** Если `platform-api2.max.ru` отвечает сертификатом,
подписанным этим УЦ (в проекте так и зафиксировано — см. `.env.example`),
стандартное хранилище (набор Mozilla, который кладут в `python:3.11-slim` /
`ca-certificates` Debian) его не знает, и бот падает на старте с ошибкой:

```
MAX API недоступен ([0] connection_error: Cannot connect to host
platform-api2.max.ru:443 ssl:True [SSLCertVerificationError: (1,
'[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed:
unable to get local issuer certificate (_ssl.c:1016)')]).
```

Бот автоматически подхватывает `certs/max_ca_bundle.crt` и добавляет его
в контекст проверки TLS **поверх** системного хранилища — проверка
сертификата при этом остаётся включённой. Переопределить можно через
`MAX_SSL_CA_BUNDLE` (путь к PEM-файлу, каталог с `.crt`/`.pem` или сам
PEM-текст), отключить — `MAX_SSL_CA_BUNDLE=none`.

## Источник и отпечатки

Скачано с официального CDN Госуслуг (`gu-st.ru` — статика `gosuslugi.ru`):

| Сертификат | URL | Действует до | SHA256 Fingerprint |
|---|---|---|---|
| Russian Trusted Root CA | `https://gu-st.ru/content/lending/russian_trusted_root_ca_pem.crt` | 2032-02-27 | `71:64:5A:DD:B4:F1:BA:D5:0E:5B:F7:63:65:14:4E:FF:AF:9B:B7:35:D6:E8:C0:CA:43:64:B5:B8:E0:00:B6:CD` |
| Russian Trusted Sub CA | `https://gu-st.ru/content/lending/russian_trusted_sub_ca_pem.crt` | 2027-03-06 | `BB:BD:E2:10:3E:79:0B:99:9E:C6:2B:D0:3C:F6:25:A5:A2:E7:C3:16:E1:0A:FE:6A:49:0E:ED:EA:D8:B3:FD:9B` |

Проверка перед использованием:

```bash
openssl x509 -in certs/max_ca_bundle.crt -noout -subject -issuer -dates -fingerprint -sha256
openssl verify -CAfile certs/max_ca_bundle.crt certs/max_ca_bundle.crt   # суб-CA подписан рутом
```

## Установка в системное хранилище (по желанию)

Если хочется, чтобы сертификату доверял весь контейнер/хост, а не только
бот (curl, pip, другие сервисы):

```bash
# Debian/Ubuntu (в Dockerfile — см. комментарий там)
sudo cp certs/max_ca_bundle.crt /usr/local/share/ca-certificates/russian_trusted_ca.crt
sudo update-ca-certificates
```

`MAX_SSL_VERIFY=false` остаётся крайним вариантом для закрытого контура:
проверка сертификата отключается полностью — так делать не стоит.
