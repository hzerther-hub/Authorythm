---
name: script-rewriter
description: Romanı biçimlendirilmiş senaryoya yeniden yazma metodolojisi ve kuralları
---

# Senaryo Yeniden Yazma Rehberi

## Yeniden Yazma İlkeleri

1. **Temel olay örgüsünü koru**: ana hikâye hattı ve karakter ilişkileri değiştirilmez
2. **Görsel hissi güçlendir**: anlatıcı metinler, görselleştirilebilir sahne betimlerine dönüştürülür
3. **Diyalog güdümlü**: olay örgüsü diyalogla ilerletilir, anlatıcı metin azaltılır
4. **Tempo kontrolü**: her sahne 30-60 saniyede tutulur, kısa videoya uygun olur
5. **Kamera dili yazılmaz**: plan ölçeği, açı, kamera hareketine girilmez; bunlar storyboard çözümleme adımına aittir

## Biçimlendirilmiş Senaryo Biçimi

```
## S01 | İÇ · Kahve Dükkanı | Akşamüstü

Akşamüstü ışığı yerden tavana uzanan pencerelerden kahve dükkanına dökülüyor, tezgâhın üzerindeki kahve fincanlarından buhar yükseliyor.

Emre köşedeki oturma alanında tek başına oturuyor, başı telefonunda, yüzünde hafif bir endişe var.

Kapı zili çalıyor, Zeynep kapıyı iterek içeri giriyor. Emre'yi görüyor ve gülümseyerek yanına yürüyor.

Zeynep: (gülümseyerek) Çok mu beklettin?
Emre: (başını kaldırarak) Yok, yeni geldim.
```

### Biçim Kuralları

- `## S[numara] | İÇ/DIŞ · Mekân | Zaman dilimi` — sahne başlığı
- Eylem betimi doğal paragraflar hâlinde — her tür kamera dili içermez
- "KarakterAdı: (durum/ifade) replik içeriği" — diyalog biçimi

### İçerik Hacmi Referansı

Biçimlendirilmiş senaryo, özgün içeriğe göre yaklaşık %20-30 daha uzundur; artış başlıca sahne başlığı işaretlerinden ve diyalog biçimlendirmesinden gelir, metin şişirme değildir.

## Yeniden Yazma Adımları

1. Önce `read_episode_script` çağırarak özgün içeriği oku
2. İçeriğin yapısını analiz et (diyalog, anlatım, iç dünya betimlerinin oranı)
3. `rewrite_to_screenplay` çağırarak yeniden yazımı gerçekleştir
4. Yeniden yazım sonucunu kontrol et, biçimlendirilmiş senaryo biçimine uyduğunu doğrula
5. `save_script` çağırarak nihai sonucu kaydet

## Dikkat Edilecekler

- İç dünya betimleri karakterin ifadesi/eylemi/tercihi veya söylenen sözlerle dışa vurulmalıdır — **seslendirme (voice-over), anlatım ve iç ses yasaktır**
- Her sahnede en az iki karakter kameranın önünde birbiriyle etkileşimde olmalı; tek kişinin boş bir odada kendi kendine konuştuğu sahne yazmayın
- Ardışık sahnelerde yer ya da saat değişmeli; aynı odayı üst üste kullanmayın
- Uzun anlatım paragrafları birden çok kısa sahneye bölünür
- Her sahnenin net bir duygu dönüm noktası olduğundan emin ol
- Karakterlerin dil üslubunun tutarlılığını koru
- Sahne numaraları kesintisiz artar (S01, S02, S03...)
- Zaman dilimleri somut olmalıdır (akşamüstü, gece yarısı, sabahın erken saati); belirsiz "gündüz" yazılmaz
