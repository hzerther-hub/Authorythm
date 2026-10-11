---
name: character-prompt
description: Standar prompt akhir karakter — close-up wajah bagian depan + three-view turnaround (tampak depan/samping 90 derajat/belakang), sebagai jangkar penampilan untuk seluruh pembuatan berikutnya
---

# Prompt Akhir Karakter (kiri: close-up wajah bagian depan + kanan: three-view turnaround)

Yang dihasilkan adalah sebuah **character turnaround sheet (lembar referensi karakter / character reference sheet, layout concept art multi-view)** dengan komposisi yang terkunci ketat:

- **Kiri: close-up wajah bagian depan** — bidikan dekat frontal kepala dan bahu, fitur wajah, gaya rambut, dan tekstur kulit terlihat jelas, sebagai jangkar pengenalan wajah
- **Kanan: tiga full-body view setinggi sama yang dipajang berjajar — tampak depan, samping 90 derajat, dan belakang** — tiga tampak seluruh tubuh dari karakter yang sama, sama tinggi dan sejajar, puncak kepala dan telapak kaki segaris

**Prinsip inti: konsistensi > keindahan.** Gambar ini adalah jangkar penampilan untuk seluruh gambar karakter dan referensi video berikutnya; harus netral, jernih, dan dapat dipakai ulang — jangan mengejar kesan artistik satu gambar.

## Struktur Output (susun menjadi satu paragraf padu mengikuti urutan ini, bahasanya mengikuti instruksi bahasa sesi)

```
character turnaround sheet, character reference sheet, multi-view concept art layout, orthographic views, no perspective distortion;
sisi kiri close-up wajah bagian depan, sisi kanan tiga full-body view setinggi sama berjajar
memperlihatkan tampak depan, samping 90 derajat, dan belakang;
tiga full-body view evenly spaced panels, puncak kepala dan telapak kaki segaris;
close-up dan full-body view adalah karakter yang sama, seluruh tubuh masuk frame, berdiri netral A-pose, ekspresi natural tanpa menampilkan emosi;
[kesan usia + kesan gender + postur tubuh], [ciri fitur wajah], [gaya rambut], [pakaian + aksesori],
wajah, gaya rambut, dan pakaian pada close-up wajah depan serta tiga view sepenuhnya identik,
latar putih bersih, cahaya lembut merata, kualitas sinematik
```

## Aturan Urutan Deskripsi

Letakkan **ciri paling khas di bagian depan**, wujudkan setiap elemen kunci dari `appearance` (penampilan) dan `styling` (tata rias dan busana) mengikuti urutan ini, tanpa ada yang terlewat:

1. Jangkar identitas: kesan usia (misalnya "awal dua puluhan"), kesan gender, postur tubuh (tinggi pendek gemuk kurus, kebiasaan sikap)
2. Fitur wajah: bentuk wajah, mata, ciri menonjol lainnya (bekas luka, tahi lalat, kacamata, dsb.) — close-up wajah depan sangat bergantung pada bagian deskripsi ini
3. Gaya rambut: warna, panjang, model
4. Pakaian: model, warna, material, kondisi (misalnya "baju kerja kusut dengan bekas solder di ujung lengan")
5. Aksesori: hanya tuliskan yang mencolok identitasnya, jangan menumpuk-numpuk

Ciri kepribadian karakter harus diubah menjadi deskripsi watak luar dan ekspresi (misalnya "rapuh dan lelah" → "tatapan mata lelah, bahu sedikit merosot"), kata-kata kepribadian tidak boleh muncul secara langsung.

## Komposisi dan Konsistensi

- Close-up wajah depan di kiri: menghadap kamera frontal, ekspresi netral, kepala hingga bahu masuk frame secara utuh
- Tiga full-body view di kanan: tampak depan, samping 90 derajat, dan belakang dari karakter yang sama, **setinggi sama, sejajar, jarak antar panel rata**, puncak kepala dan telapak kaki berada pada satu garis mendatar yang sama
- Close-up dan tiga full-body view harus memiliki wajah yang sama, gaya rambut yang sama, pakaian yang sama — tuliskan secara eksplisit "wajah, gaya rambut, dan pakaian pada close-up wajah depan dan tiga full-body view sepenuhnya identik"
- Berdiri netral, ekspresi natural — agar mudah dipakai ulang sebagai gambar referensi
- Tangan dan kaki normal: tangan pada full-body view berjumlah lima jari yang normal, kaki lima jari, dua lengan dua kaki, tanpa anggota tubuh berlebih; tangan rileks secara alami, jangan gestur yang rumit (menurunkan peluang tangan tergambar cacat)
- **Batas keras total instansi karakter: 1 close-up wajah depan + 3 full-body view = total 4 instansi karakter, dilarang lebih dari itu** (perhatikan: 3 full-body view itu sendiri adalah karakter yang sama dari sudut berbeda — tampak depan / samping 90 derajat / belakang, ini adalah niat desain dan bukan "duplikasi"; yang dilarang adalah menggambar karakter yang sama sekali lagi di luar itu, atau menyisipkan instansi lain satu frame di luar 3 full-body view; di antara 3 full-body view harus tampak arah hadap yang jelas berbeda, kiri / tengah / kanan masing-masing adalah tampak depan / samping 90 derajat / belakang, tidak boleh semuanya tampak depan)
- Satu orang saja: seluruh gambar hanya boleh memuat 4 instansi karakter di atas, tanpa bayangan ganda, kembar, atau replikasi multi-orang; fitur wajah stabil, tidak cacat, tidak meleleh
- Cahaya studio lembut merata, jangan cahaya-bayangan yang dramatis (gambar referensi harus dapat dipakai di segala jenis adegan)
- Output menggunakan bahasa target yang ditentukan instruksi bahasa sesi, jangan mencampur kata-kata yang tidak relevan

## Larangan

- Pose dinamis, ekspresi berlebihan, memegang prop, berada dalam satu frame dengan orang lain
- **Instansi karakter lebih dari 4 (1 close-up + 3 full-body view); 3 full-body view adalah karakter yang sama dari sudut berbeda (tampak depan / samping 90 derajat / belakang) — ini adalah niat desain, bukan larangan; yang dilarang adalah menduplikasi karakter yang sama lagi di luar 3 full-body view, atau menggambar ketiga full-body view semuanya tampak depan / semuanya menumpuk di tengah frame / bertumpuk / setinggi berbeda**
- Memotong tubuh (full-body view harus full body, kepala hingga telapak kaki masuk frame utuh; close-up harus kepala dan bahu masuk frame utuh)
- Enam jari, jari menyatu, jari hilang, cacat menyatu; tiga tangan, tiga kaki, anggota tubuh berlebih, distorsi replikasi
- Bayangan ganda, kembar, replikasi multi-orang; fitur wajah cacat, wajah meleleh
- Teks, label, watermark, tanda tangan; logo merek nyata, wajah artis kenyataan
- Bayangan tebal, cahaya latar berwarna, prop latar

## Penyimpanan

