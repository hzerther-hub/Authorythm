---
name: storyboard-breaker
description: Storyboard çözümleme zanaatı — senaryoyu birden çok alt plan taşıyabilen storyboard parçalarına bölme
---

# Storyboard Çözümleme Rehberi

## Temel Tanım: Storyboard Parçası

Bir storyboard ＝ bir **storyboard parçası** (segment) ＝ bir video üretim görevi.

- Her parça **8-15 saniye** uzunluğundadır ve içinde **2-4 alt plan** taşır
- Alt planlar arasında **kesme yapılabilir**: plan ölçeği, açı ya da çekim öznesi değişir, sert kesmeyle birleştirilir
- Alt planlar **sahne dışına çıkmaz**: bir parça tek bir sahnenin içinde geçer (`scene_id` parça düzeyinde bağlanır)
- Her alt plan 2-6 saniyedir, tek bir görsel birime odaklanır (bir eylem, bir tepki, bir yakın çekim)

## Çözümleme Süreci (dört adım)

2. **Ritim (beat) tanıma**: önce senaryonun anlatı ritimlerini tanı — senaryodaki 【Açılış】【Tetik】【Doruk】【Kapanış】 gibi işaretler ya da anlatı dönüm noktaları (mekân değişimi, kuralın ifşası, duygu patlaması, ters dönüş). **Ritim sınırları parça kesmesini zorunlu kılar**; aynı ritim içindeki alt planlar öncelikle aynı parçaya alınır, bir neden-sonuç zinciri (zemin hazırlama-olma-tepki) farklı parçalara dağıtılmaz
3. **Toplam hacim çapası**: hedef toplam süre ＝ senaryo karakter sayısı ÷ 500 karakter/dakika; parça sayısı ≈ hedef toplam süre ÷ 12 saniye, ±20% dalgalanma serbesttir. Belirgin biçimde aşmak ya da eksik kalmak yoktur

## Tempo Katmanlarına Göre Süre

Süreyi parçanın işlevine göre belirle, tek kalıba sokma:

| Parça türü | Süre | Açıklama |
|---|---|---|
| Geçiş parçası | 8-10 saniye | Yol alma, boş çekim, ortam kuruluşu, sahne geçişi |
| Anlatı parçası | 10-15 saniye | Olağan olay ilerlemesi, diyalog |
| Patlama parçası | 12-15 saniye | Yakın çekim, kuralın ifşası, duygu patlaması, ters dönüş; alt plan temposu yavaşlatılır, tek bir alt plan 4-6 saniye kalabilir |

## Diyalog Süresi Alt Sınırı (zorunlu kural)

**Parça süresi ≥ parçadaki replik ve anlatıcı metnin toplam karakter sayısı (description içinde yazılan kısım) ÷ 4.5 karakter/saniye + 2 saniye oyunculuk payı**

Sığmayan replikler bir sonraki parçaya bölünmek zorundadır; oynanamayacak replikleri tek bir parçaya tıkıştırmak yasaktır.

## Plan Öğeleri

1. **Plan başlığı**: parçanın temel içeriğini 3-5 kelimelik özetleyen ad (ör. "Kâbusla uyanış")
2. **Zaman**: somut saat bilgisi + ışık betimi
3. **Mekân**: sahnenin eksiksiz betimi + mekânsal düzen + çevre ayrıntıları
4. **Plan ölçeği**: parçada egemen olan plan ölçeği; çok ölçekli parçalarda bileşim yazılır, ör. "orta plan+yakın çekim"
5. **Açı**: göz hizası / aşağıdan (alçak açı) / yukarıdan (yüksek açı) / yandan / arkadan
6. **Kamera hareketi** `movement`: her alt planda bir kamera hareketi bulunur, söz dağından seçilerek yazılır (bir parçadaki farklı alt planlar farklı olabilir). Söz dağı: sabit kamera mikro hareket (nefes dalgalanması) / yavaş yaklaşma / uzaklaşma / yanal takip / yükselme-alçalma ile kuşbakışı / yay dolanma / elde tutma sarsıntısı / gözetleme açısı / bakış odağı / titreme / yumuşak dolanma / yüksek hızlı kuyruklama / dövüş arası geçiş / dalış inişi / aşırı alçak açıdan çekim / Hollanda açısı / omuz üstü yakın plan / öznel bakış / hızlı savurma / örtü geçişi / ani duruş dondurma / bullet time. Parça türüne göre seçim: zemin hazırlama parçası→uzaklaşarak açığa çıkarma, yükselme-alçalma kuşbakışı, yanal takip; diyalog parçası→omuz üstü yakın plan, yavaş yaklaşma, nefes dalgalanması; duygu parçası→kalp atışı nabzı tarzı yavaş yaklaşma, elde tutma sarsıntısı, titreme; eylem parçası→dövüş/yüksek hızlı eylemde önce fight-cinematography becerisinden kamera konumu formülü seçilir, ötekilerde yüksek hızlı kuyruklama, dövüş arası geçiş, yanal takip; patlama parçası→bullet time, ani duruş dondurma, bakış odağı; gerilim/korku→gözetleme açısı, Hollanda açısı, öznel bakış. Vurgu numaraları (bullet time/ağır çekim/balık gözü) bölüm başına en fazla 1-2 kez
7. **Görüntü betimi** `description`: `【镜头1】…【镜头2】…` biçiminde alt plan alt plan, seyircinin gerçekten gördüğünü ve duyduğunu betimler — çekimin nasıl yapıldığı (kamera hareketi, ör. "kamera orta plandan yakın çekime sabit hızla yavaşça yaklaşıyor") alt planın başında, görüntü (kim + somut eylem + beden dili ayrıntıları + ifade) ise kamera hareketinden sonra yazılır; alt planda replik varsa "KarakterAdı der: "replik"" biçiminde ilgili `【镜头N】` içinde, anlatıcı metni ise "Anlatıcı: içerik" biçiminde yazılır
8. **Görüntü sonucu** `result`: parçanın sonundaki anlık sonuç + görsel ayrıntılar
9. **Atmosfer** `atmosphere`: ışık + renk tonu + ses + genel atmosfer
10. **Süre** `duration`: parça toplam süresi 8-15 saniye ve diyalog süresi alt sınırını karşılamalıdır
11. **Sahne bağlama**: mevcut bir sahneyle eşleştirilebiliyorsa `scene_id` mutlaka doldurulur
12. **Karakter bağlama**: `character_ids` doldurulur; bu parçada yer alan 0 ile çok sayıda karakter bağlanır
13. **Öğe bağlama**: `prop_ids` doldurulur; bu parçada görünen kilit öğeler bağlanır (0 ile çok sayıda)

## Sahne Bağlama Kuralları

- `location + time` net biçimde eşleşiyorsa doğru `scene_id` mutlaka geri doldurulur
- Var olmayan sahne ID'leri uydurulmaz
- Senaryo içeriği açıkça mevcut bir sahnenin içinde geçiyorsa, yinelenen yeni bir sahne betimi oluşturulmaz

## Karakter Bağlama Kuralları

- Bir parça karaktersiz olabilir ya da birden çok karakter bağlayabilir
- Parçada net biçimde görünen, görülen, eylem yapan ya da konuşan her karakter bağlanmalıdır
- Salt çevre parçaları, boş çekimler ve eşya yakın çekimleri boş dizi geçebilir

## Öğe Bağlama Kuralları

- Öğe bir karakter tarafından kullanılıyor, el değiştiriyor, yakın çekimde veriliyorsa ya da karede belirgin görünürken anlatıya anlam katıyorsa mutlaka bu parçaya bağlanır
- Öğe yakın çekim parçaları (karaktersiz) de öğeyi bağlamalıdır; `character_ids` boş olabilir
- Olay örgüsüyle ilgisi olmayan arka plan eşyaları ve sahne dekoru bağlanmaz; öğe görünmeyen parçalar boş dizi geçer
- Bağlanan öğeler, video üretimi için referans görsel (beyaz fonlu tekil ürün görseli) olarak kullanılır; öğenin görünümünün parçalar arası tutarlılığını garanti eder

## Kalite Koşulları

- `description` insan tarafından okunabilir olmalı; alt plan alt plan seyircinin gerçekten gördüğünü ve duyduğunu betimlemelidir; replikler/anlatıcı metni doğrudan ilgili `【镜头N】` içinde yazılır
- `image_prompt`, tek karelik kompozisyonu, karakter görünümünü, ortamı ve ışığı öne çıkarmalıdır (parçanın ilk alt planına karşılık gelir)
- `bgm_prompt` ve `sound_effect` kısa ve öz ifadeler olabilir; ama yalnızca "gergin" ya da "üzgün" kadar boş olamaz
- Ayarlama gerekiyorsa `update_storyboard` çağırarak ilgili parçayı değiştir

## Doğallık ve Kimlik Makullüğü (zorunlu kurallar)

- `description` / `result` doğal bir görüntü anlatımı diliyle yazılmalıdır: yalnızca seyircinin gördüğü ve duyduğu yazılır; analitik üslup ve madde madde sıralama ("öncelikle/sonra", "1、2、3" tarzı izahat) yasaktır; `【镜头N】` numaraları izin verilen tek yapısal işarettir
- Kişilerin davranışları kimlik, yaş ve yetenek kurgusuna uymalıdır: okuma yazma bilmeyen biri okuma yazma bilmez; yazı yazma, mektup okuma, metin okuma gibi eylemler görünemez; küçük yaştaki çocuklar için de yazı yazma mantığı görünemez; yabancı dil bilmeyen karakter yabancı dil okuyup yazamaz. Tek istisna, senaryonun özgün metninde bu davranışın açıkça yazılı olmasıdır — senaryo yazmadıysa kendiliğinden eklenmez
- Okuma yazma/hesap yapma gibi mesleki yetenek dayanağı yoksa, duygu ve bilgi aktarımı eylem, yüz ifadesi, öğe gibi yollarla yapılır; "yazı yazma/yazı okuma"ya indirilmez
