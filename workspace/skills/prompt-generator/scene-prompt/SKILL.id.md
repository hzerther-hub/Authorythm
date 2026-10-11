---
name: scene-prompt
description: Standar prompt akhir latar — establishing shot wide-angle yang jernih: posisi relatif tetap foreground/midground/background/pintu masuk/lantai/dinding/tata letak utama, struktur ruang kontinu, konsisten, dan dapat dipakai ulang, tanpa tokoh
---

# Prompt Akhir Latar (establishing shot wide-angle · empty shot tanpa tokoh)

Yang dihasilkan adalah sebuah gambar latar **establishing shot wide-angle yang jernih**: empty shot latar murni **tanpa satu pun tokoh**, memperlihatkan secara utuh **posisi relatif yang tetap dari foreground, midground, background, pintu masuk/keluar, lantai, dinding, dan tata letak utama**, struktur ruangnya kontinu, konsisten, dan dapat dipakai ulang.

Gambar ini akan menjadi jangkar referensi latar belakang untuk seluruh shot di latar tersebut: penonton maupun model sama-sama harus dapat membaca tata ruang keseluruhan dari gambar ini — lewat mana orang masuk dan keluar, seperti apa tekstur lantai dan dinding, di posisi mana setiap tata letak inti diletakkan secara tetap. Sudut pandang harus stabil dan serbaguna.

## Struktur Output (susun menjadi satu paragraf padu mengikuti urutan ini, bahasanya mengikuti instruksi bahasa sesi)

```
Shot wide-angle kamera tetap, establishing shot yang jernih, [lokasi + tekstur era], [rentang waktu],
komposisi tiga lapis foreground ([elemen foreground]), midground ([ruang utama midground]), background ([kedalaman ruang background]),
pintu masuk/keluar ([posisi dan gaya pintu/jalur]), lantai ([material dan kondisi lantai]), dinding ([material dan warna dinding]),
[tata letak utama beserta posisi relatif tetapnya],
struktur ruang kontinu dan konsisten,
[sumber cahaya + suhu warna + kontras terang-gelap], [suasana],
tidak ada satu pun tokoh manusia dalam frame, latar kosong, kualitas sinematik
```

## Aturan Struktur Ruang

Ruang harus **dapat dibaca, saling cocok, dan dapat dipakai ulang**:

- **Foreground**: pembingkai/penutup pandangan (kusen pintu, sudut meja, tanaman, tepi peralatan) yang menciptakan kedalaman — tuliskan 1-2 elemen konkret
- **Midground**: ruang utama latar dan tata letak inti (jalur perakitan, ranjang, konter)
- **Background**: perpanjangan ruang (dinding di kejauhan, jendela, koridor, siluet kota)
- **Pintu masuk/keluar**: posisi dan gaya pintu, tangga, jalur harus eksplisit (misalnya "sebuah pintu besi di sisi kiri frame"), inilah dasar penataan keluar-masuknya tokoh pada shot-shot berikutnya
- **Lantai dan dinding**: material, warna, kondisi dibuat konkret (misalnya "lantai semen berbekas noda oli", "dinding plester kapur berbintik-bintik")
- **Tata letak utama**: tuliskan 2-4 tata letak inti beserta **posisi relatif tetapnya** (misalnya "jalur perakitan tersusun di sepanjang dinding, ujungnya adalah bar"), relasi kiri-kanan/dekat-jauh antar tata letak harus konsisten, jangan hanya menghafalkan daftar nama barang

## Tokoh (Aturan Mutlak · Prioritas Tertinggi)

**Tidak boleh ada satu pun orang manusia dalam gambar latar, hanya latar itu sendiri yang dipertahankan.**

- Prompt tidak mendeskripsikan tokoh, jangan menyebut apa pun yang berkaitan dengan tokoh
- Informasi tokoh apa pun yang muncul dalam deskripsi latar (prompt) diabaikan semua, tidak ditulis ke dalam prompt
- Akhir prompt harus memuat: "tidak ada satu pun tokoh manusia dalam frame, latar kosong"

Tata letak, tekstur era, dan elemen visual kunci dalam `prompt` (deskripsi latar) harus seluruhnya diwujudkan; `lighting` (cahaya dan bayangan latar) dibuat konkret: arah sumber cahaya, dingin-hangatnya suhu warna, kontras terang-gelap (misalnya "lampu tabung di langit-langit memancarkan cahaya putih dingin, membayangi keras di bawah mesin").

## Sudut Pandang dan Suasana

- Bidikan wide setara mata atau sedikit dari atas yang stabil, jangan sudut ekstrem ke atas/bawah, fisheye, atau komposisi miring (akan dipakai ulang berulang kali sebagai latar tetap)
- Rentang waktu dan nada cahaya ditentukan oleh `location` + `time` (cahaya siang/malam/senja benar-benar berbeda)
- Kata suasana dibuat konkret: "menindih" → "udara pengap, cahaya redup dan suram", jangan hanya menulis kata emosi abstrak
- Output menggunakan bahasa target yang ditentukan instruksi bahasa sesi, jangan mencampur kata-kata yang tidak relevan

## Larangan

- Tokoh apa pun — **tidak boleh ada satu pun orang manusia dalam gambar latar, hanya latar itu sendiri yang dipertahankan**
- Teks, teks terbaca pada papan nama, watermark, tanda tangan, logo merek nyata
- Motion blur, benda yang sedang bergerak (gambar referensi latar harus diam dan stabil)
- Hanya menghafalkan daftar tata letak tanpa menjelaskan posisi relatifnya (struktur ruang harus kontinu dan konsisten)

## Penyimpanan

