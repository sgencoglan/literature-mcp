# Güvenlik

## Kapsam

Bu depo yerel MCP sunucuları ve rapor üreticisi içerir. PDF indirmez, ödeme
duvarını veya erişim kontrolünü aşmaz. Tam metinler kullanıcı hesabından
indirilir ve yerel olarak işlenir.

## Bildirim

Güvenlik açığı, kişisel veri sızıntısı veya yayımlanmamış metin içeren bir
dosya fark ederseniz public issue açmayın. Depo sahibine GitHub üzerinden özel
mesaj gönderin.

## Desteklenen sürüm

Yalnızca en son `v2.x` sürümü güvenlik düzeltmeleri alır.

## Temizlik güvenliği

`chapter-report cleanup` yalnızca manifestte listelenen, proje klasörü içindeki
dosyaları siler. Path traversal, mutlak yol ve hash uyuşmazlığı reddedilir.
PDF, indeks, `projects.json` ve manifest dışı dosyalar silinmez.
