---
name: prop-prompt
description: Öğe (prop) nihai prompt standardı — beyaz fonlu tekil öğe natürmort, standart ürün fotoğrafçılığı açısı: doğru oranlar, eksiksiz kenarlar, anlatı taşımayan arka plan
---

# Öğe Nihai Promptu (beyaz fonlu tekil öğe · standart ürün fotoğrafçılığı)

Üretilen, beyaz fonlu tekil bir ürün görselidir (product shot): **standart ürün fotoğrafçılığı açısı** kullanılır, karede yalnızca öğenin kendisi bulunur, saf beyaz bir arka plan üzerinde yalıtılmış şekilde yer alır, **başka hiçbir öğe karıştırılmaz** — başka eşya yok, insan yok, sahne ortamı yok, tutan el yok.

Üç zorunlu koşul:
1. **Eşyanın tüm bölümlerinin oranı doğru** — abartma, bozma ya da üslubi uzatma yok; öğenin göreli boyut ilişkileri gerçek olmalı
2. **Kenarlar eksiksiz** — öğe bütünüyle karede, dört tarafında pay bırakılmış; hiçbir bölümü kare kenarıyla kırpılamaz
3. **Arka plan hiçbir anlatı içeriği taşımaz** — saf beyaz arka plan yalnızca bir zalandır; sahne hissi taşımaz, olay iması taşımaz, dekoratif öğe taşımaz

## Çıktı Yapısı (bu sırayla tek parça akıcı bir betim kur, dil oturum dil yönergesini izler)

```
tek öğeli ürün görseli, standart ürün fotoğrafçılığı açısı, [öğe adı + malzeme/renk/şekil/boyut + eskilik derecesi ve yıpranma ayrıntıları],
eşyanın tüm bölümlerinin oranı doğru, saf beyaz arka plan üzerinde yalıtılmış biçimde yerleştirilmiş, ortalanmış ve eksiksiz karede, kenarlar eksiksiz kırpılmamış,
arka plan tertemiz ve hiçbir anlatı içeriği taşımıyor, başka eşya yok, insan yok, sahne yok,
yumuşak ve eşit dağılımlı stüdyo ışığı, hafif gölgeler, yüksek ayrıntı
```

## Üretim Kuralları

- Öğenin `name` (ad) ve `description` (eşyanın dış görünüşü) alanlarını çekirdek al: malzeme, renk, şekil, boyut, eskilik derecesi, yıpranma izleri gibi fiziksel ayrıntılar **madde madde işlenir**; bunlar öğenin tanınırlığının kaynağıdır
- Standart ürün fotoğrafçılığı açısı: hafif tepeden 3/4 açı (tepe yüzeyi ve yan yüzey aynı anda görülür, en iyi hacim hissi verir); düz öğeler (kâğıt, kimlik belgesi, fotoğraf) için tam tepeden düz yerleşim (flat lay)
- Tek öğe ortalanmış ve eksiksiz sunulur, dört tarafta pay bırakılır, oranlar doğru, kenarlar eksiksiz; öğenin gövdesi kırpılmaz
- Yumuşak ve eşit dağılımlı stüdyo ışığı, hafif gölgeler, yüksek ayrıntı
- Yalnızca eşyanın kendisi betimlenir; olay örgüsünden, karakterlerden ya da kullanım amacından söz edilmez (ne arka plan ne kare anlatı içeriği taşır)
- Çıktı, oturum dil yönergesinin belirlediği hedef dilde verilir, ilgisiz sözcükler karıştırılmaz; **"sinematik doku" türü sözcükler kullanılmaz** (öğe görseli bir ürün çekimidir, film karesi değil)

## Yasaklar

- Tutulduğu hâldeki ellerin, insanların, başka eşyaların ya da sahne ortamının kareye girmesi
- Ambalaj, kaide, sergi standı (öğenin bizzat kendisinin bir parçası değilse)
- Yazı, filigran, imza, gerçek marka logoları (öğenin bizzat üzerinde basılı yazı ve desenler korunabilir ve betimlenebilir)
- Ortam yansımaları, renkli ışık
- Abartılı perspektif, bozulma, oran hatası, kenar kırpma

## Kaydetme

