---
name: character-prompt
description: Karakter nihai prompt standardı — önden yüz yakın çekimi + üç görünüm (character turnaround: önden / 90 derece yandan / arkadan), sonraki tüm üretimler için görünüm çapası
---

# Karakter Nihai Promptu (solda önden yüz yakın çekimi + sağda üç görünüm)

Üretilen, kompozisyonu kesin biçimde sabit bir **karakter kostüm-referans görselidir (character turnaround sheet / character reference sheet, multi-view concept art layout)**:

- **Sol: önden yüz yakın çekimi** — baş ve omuzların önden yakın görünümü; yüz hatları, saç ve cilt dokusu net seçilir, yüz tanınırlığının çapasıdır
- **Sağ: önden, 90 derece yandan ve arkadan üç eşit yükseklikte tam boy görünümün yan yana sunumu** — aynı karakterin üç tam boy görünümü eşit yükseklikte yan yanadır, tepe noktaları ve ayak tabanları hizalıdır

**Temel ilke: tutarlılık > güzellik.** Bu görsel, sonraki tüm karakter görsellerinin ve video referanslarının görünüm çapasıdır; nötr, net ve yeniden kullanılabilir olmalıdır — tek bir görselin sanatsallığını arama.

## Çıktı Yapısı (bu sırayla tek parça akıcı bir betim kur, dil oturum dil yönergesini izler)

```
character turnaround sheet, character reference sheet, multi-view concept art layout, orthographic views, no perspective distortion;
solda önden yüz yakın çekimi, sağda önden / 90 derece yandan / arkadan üç eşit yükseklikte tam boy görünüm yan yana,
üç tam boy görünüm evenly spaced panels, tepe noktaları ve ayak tabanları hizalı;
yakın çekim ile tam boy görünümler aynı karakterdir, tam beden karede, A-pozu nötr duruş, ifadesini ele veren doğal olmayan ifade yok,
[yaş izlenimi + cinsiyet izlenimi + vücut yapısı], [yüz hatları], [saç stili], [kıyafet + aksesuarlar],
yakın çekim ile üç görünümün yüzü, saçı ve kıyafeti tamamen aynıdır,
düz beyaz arka plan, yumuşak ve eşit dağılımlı ışık, sinematik doku
```

## Betimleme Sırası Kuralları

**En tanınır özellikleri öne koy**, `appearance` (görünüş) ve `styling` (makyaj-kostüm) alanlarının her kilit öğesini bu sırayla işle, hiçbirini atlama:

1. Kimlik çapaları: yaş izlenimi (ör. "yirmili yaşların başı"), cinsiyet izlenimi, vücut yapısı (uzun-kısa-zayıf-şişman, duruş alışkanlıkları)
2. Yüz hatları: yüz şekli, gözler, diğer belirgin özellikler (yara izi, ben, gözlük vb.) — önden yüz yakın çekimi özellikle bu kısma dayanır
3. Saç: renk, uzunluk, stil
4. Kıyafet: kesim, renk, malzeme, durum (ör. "kol ağzında lehim izleri olan kırışık iş kıyafeti")
5. Aksesuar: yalnızca tanınır olanlar yazılır, yığma yapılmaz

Karakterin kişilik özellikleri, dışa dönük duruş ve yüz ifadesi betimlerine dönüştürülür (ör. "yorgun bitkin" → "baktıran yorgun gözler, hafif çökmüş omuzlar"); kişilik sözcükleri doğrudan geçmez.

## Kompozisyon ve Tutarlılık

- Soldaki önden yüz yakın çekimi: kameraya tam önden bakar, nötr ifade, tepeden omuza kadar eksiksiz karede
- Sağdaki üç tam boy görünüm: aynı karakterin önden, 90 derece yandan ve arkadan görünümü, **eşit yükseklikte yan yana, araları eşit**, tepe noktaları ve ayak tabanları aynı yatay çizgide
- Yakın çekim ile üç tam boy görünüm aynı yüze, aynı saça, aynı kıyafete sahip olmalıdır — "yakın çekim ile üç tam boy görünümün yüzü, saçı ve kıyafeti tamamen aynıdır" ifadesi açıkça yazılır
- Nötr duruş, doğal ifade — referans görsel olarak yeniden kullanımı kolaylaştırır
- El ve ayaklar normal: tam boy görünümlerde eller beş parmak, ayaklar beş ayak parmağı, iki kol iki bacak; fazla uzuv yok; eller doğal ve gevşek, karmaşık el hareketi yok (elde el çizim bozukluğu olasılığını düşürür)
- **Karakter örneği toplam sert üst sınırı: 1 önden yüz yakın çekimi + 3 tam boy görünüm = toplam 4 karakter örneği, daha fazlası yasaktır** (dikkat: 3 tam boy görünümün kendisi aynı karakterin farklı açılarıdır — önden / 90 derece yandan / arkadan; bu tasarım niyetidir, "kopya" değildir; yasak olan, aynı karakterin ayrıca bir kez daha çizilmesi ya da 3 tam boy görünümün dışında kadraja ek örnek sıkıştırılmasıdır; 3 tam boy görünüm birbirinden açık biçimde farklı yönelimler göstermelidir, sırayla soldan sağa önden / 90 derece yandan / arkadandır, kesinlikle üçü de önden olamaz)
- Tekil kişi: görselin tamamında yalnızca yukarıdaki 4 karakter örneği bulunur; gölge kopya, ikiz, çoklu kişi kopyası yoktur; yüz hatları stabildir, bozulma ve erime olmaz
- Yumuşak ve eşit dağılımlı stüdyo ışığı; dramatik ışık-gölge yok (referans görsel her tür sahnede kullanılabilmelidir)
- Çıktı, oturum dil yönergesinin belirlediği hedef dilde verilir, ilgisiz sözcükler karıştırılmaz

## Yasaklar

- Dinamik pozlar, abartılı ifadeler, elde tutulan eşyalar, başka kişilerle aynı karede bulunma
- **4 karakter örneğini aşmak (1 yakın çekim + 3 tam boy görünüm); 3 tam boy görünüm aynı karakterin farklı açılarıdır (önden / 90 derece yandan / arkadan) — bu tasarım niyetidir, yasaklı öğe değildir; yasak olan: 3 tam boy görünümün dışında aynı karakterden ek kopya çizmek ya da 3 tam boy görünümün üçünü de önden çizmek / üçünü kadraja ortada yığmak / üst üste bindirmek / farklı yüksekliklerde sunmak**
- Bedeni kırpmak (tam boy görünümler tam boy olmalı, tepe noktasından ayak tabanına eksiksiz karede; yakın çekimde baş ve omuzlar eksiksiz karede olmalı)
- Altıncı parmak, birleşik parmak, eksik parmak, birleşme bozukluğu; üç el, üç bacak, fazla uzuv, kopya bozulması
- Gölge kopya, ikiz, çoklu kişi kopyası; yüz hatlarında bozulma, yüz erimesi
- Yazı, etiket, filigran, imza; gerçek marka logoları, gerçek ünlü yüzleri
- Ağır gölgeler, renkli arka plan ışığı, arka plan eşyaları

## Kaydetme

