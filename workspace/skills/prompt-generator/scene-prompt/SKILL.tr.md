---
name: scene-prompt
description: Sahne nihai prompt standardı — net geniş açılı kuruluş çekimi (establishing shot): ön plan/orta plan/arka plan/giriş-çıkışlar/zemin/duvarlar/ana dekorun sabit göreli konumları; mekân kesintisiz, öz tutarlı ve yeniden kullanılabilir, insan yok
---

# Sahne Nihai Promptu (geniş açılı kuruluş çekimi · insansız boş çekim)

Üretilen, **net bir geniş açılı kuruluş çekimi (establishing shot)** sahne görselidir: **kesinlikle insan bulunmayan** salt sahne boş çekimi; **ön plan, orta plan, arka plan, giriş-çıkışlar, zemin, duvarlar ve ana dekorun sabit göreli konumlarını** eksiksiz gösterir; mekânsal yapı kesintisiz, öz tutarlı ve yeniden kullanılabilirdir.

Bu görsel, sahnenin tüm çekimleri için arka plan referans çapası olarak kullanılır: seyircinin de modelin de tüm mekân düzenini bu görselden okuyabilmesi gerekir — nereden girilip çıkıldığı, zemin ve duvarların dokusu, temel dekorun her birinin hangi konumda sabitlendiği. Bakış açısı stabil ve genel amaçlı olmalıdır.

## Çıktı Yapısı (bu sırayla tek parça akıcı bir betim kur, dil oturum dil yönergesini izler)

```
sabit kamera geniş açı çekim, net kuruluş çekimi, [mekân + dönem dokusu], [zaman dilimi],
ön plan ([ön plan öğeleri]), orta plan ([orta planın ana mekânı]), arka plan ([arka planın derinliği]) üç katmanlı kompozisyon,
giriş-çıkışlar ([kapı/geçidin konumu ve biçimi]), zemin ([zemin malzemesi ve durumu]), duvarlar ([duvar malzemesi ve rengi]),
[ana dekor ve sabit göreli konumları],
mekânsal yapı kesintisiz ve öz tutarlı,
[ışık kaynakları + renk sıcaklığı + aydınlık-karanlık karşıtlığı], [atmosfer],
karede hiç insan yok, boş sahne, sinematik doku
```

## Mekânsal Yapı Kuralları

Mekân **okunabilir, eşleşebilir ve yeniden kullanılabilir** olmalıdır:

- **Ön plan**: çerçeveleme/örteç öğeler (kapı pervazı, masa köşesi, bitki, ekipman kenarı), derinlik kurar — 1-2 somut öğe yazılır
- **Orta plan**: sahnenin ana mekânı ve temel dekoru (montaj hattı, yatak, tezgâh)
- **Arka plan**: mekânın uzantısı (uzaktaki duvar, pencere, koridor, şehir silüeti)
- **Giriş-çıkışlar**: kapı, merdiven, geçidin konumu ve biçimi net olmalıdır (ör. "karenin solunda bir demir kapı"); sonraki çekimlerde karakterlerin girip çıkmasının dayanağı budur
- **Zemin ve duvarlar**: malzeme, renk ve durum somutlaştırılır (ör. "yağ lekeli beton zemin", "kireç sıvası benek benek dökülmüş duvar")
- **Ana dekor**: 2-4 temel dekor parçası ve bunların **sabit göreli konumları** yazılır (ör. "montaj hattı duvar boyunca uzanır, ucunda tezgâh bulunur"); dekorlar arasındaki sol-sağ/ yakın-uzak ilişkisi öz tutarlı olmalıdır, yalnızca eşya adı sıralanmaz

## İnsanlar (zorunlu kural · en yüksek öncelik)

**Sahne görselinde hiçbir insan görünemez; yalnızca sahnenin kendisi kalır.**

- Promptta insan betimlenmez, insanla ilgili hiçbir içerik anılmaz
- Sahne betiminde (prompt) geçen insan bilgileri tamamen yok sayılır, prompta yazılmaz
- Promptun sonunda şu bulunmalıdır: "karede hiç insan yok, boş sahne"

`prompt` (sahne betimi) alanındaki dekor, dönem dokusu ve kilit görsel öğelerin tamamı işlenmelidir; `lighting` (sahnenin ışık-gölge düzeni) somutlaştırılmalıdır: ışık kaynağının yönü, renk sıcaklığının sıcak-soğuk durumu, aydınlık-karanlık karşıtlığı (ör. "tepedeki floresan soğuk beyaz ışık veriyor, makinelerin altına sert gölgeler düşürüyor").

## Bakış Açısı ve Atmosfer

- Stabil göz hizası ya da hafif tepeden geniş açı; aşırı yukarı/aşağı açılar, balık gözü, eğik kompozisyon yok (sabit sahne olarak tekrar tekrar yeniden kullanılacak)
- Zaman dilimi ve ışık temeli `location` + `time` ile belirlenir (gündüz/gece/akşamüstü ışığı birbirinden tamamen farklıdır)
- Atmosfer sözcükleri somutlaştırılır: "baskıcı" → "havası boğucu, ışığı loş ve alçak"; yalnızca soyut duygu sözcüğü yazılmaz
- Çıktı, oturum dil yönergesinin belirlediği hedef dilde verilir, ilgisiz sözcükler karıştırılmaz

## Yasaklar

- Her tür insan — **sahne görselinde hiçbir insan görünemez, yalnızca sahnenin kendisi kalır**
- Yazı, tabeladaki okunabilir yazılar, filigran, imza, gerçek marka logoları
- Hareket bulanıklığı, hareket hâlindeki nesneler (sahne referans görseli durgun ve stabil olmalıdır)
- Dekoru yalnızca listeleyip göreli konum vermemek (mekânsal yapı kesintisiz ve öz tutarlı olmalıdır)

## Kaydetme

