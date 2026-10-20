---
name: script-rewriter
description: Metodologi dan standar penulisan ulang novel menjadi skenario terformat
---

# Panduan Penulisan Ulang Skenario

## Prinsip Penulisan Ulang

1. **Pertahankan alur inti**: jangan mengubah garis utama cerita dan relasi antar karakter
2. **Perkuat kesan visual**: ubah teks naratif menjadi deskripsi adegan yang dapat divisualisasikan
3. **Bergerak dengan dialog**: gunakan dialog untuk menggerakkan cerita, kurangi narasi
4. **Kendali ritme**: setiap adegan dijaga 30-60 detik, cocok untuk video pendek
5. **Jangan menulis bahasa kamera**: jangan menyentuh ukuran shot, sudut, gerakan kamera — semua itu milik tahap pemecahan storyboard

## Format Skenario Terformat

```
## S01 | INT · Kafe | Senja

Cahaya senja menembus jendela kaca lantai-ke-atas dan berhamburan masuk ke dalam kafe, uap panas membubung dari cangkir kopi di atas bar.

Budi duduk sendirian di booth pojok, menunduk menatap ponsel, ekspresinya agak cemas.

Bel pintu berbunyi, Siti mendorong pintu dan masuk. Ia melihat Budi, berjalan mendekat sambil tersenyum.

Siti: (tersenyum) Lama menunggu?
Budi: (mendongak) Tidak juga, baru datang.
```

### Aturan Format

- `## Snomor | INT/EXT · Lokasi | Rentang waktu` — kepala adegan
- Paragraf alami deskripsi aksi — tidak memuat bahasa kamera apa pun
- `NamaKarakter: (kondisi/ekspresi) isi dialog` — format dialog

### Referensi Volume Konten

Skenario terformat bertambah sekitar 20-30% dibanding konten aslinya; pertambahan utamanya berasal dari penanda kepala adegan dan pemformatan dialog, bukan pengembangan isi.

## Langkah Penulisan Ulang

1. Panggil terlebih dahulu `read_episode_script` untuk membaca konten asli
2. Analisis struktur konten (proporsi dialog, narasi, deskripsi psikologis)
3. Panggil `rewrite_to_screenplay` untuk menjalankan penulisan ulang
4. Periksa hasil penulisan ulang, pastikan sesuai format skenario terformat
5. Panggil `save_script` untuk menyimpan hasil akhir

## Catatan

- Deskripsi psikologis wajib diekspresikan lewat ekspresi/aksi/pilihan karakter atau kalimat yang diucapkan — **voice-over, narasi, dan monolog dalam hati dilarang**
- Setiap adegan harus melibatkan minimal dua tokoh yang berinteraksi di depan kamera; jangan menulis adegan satu orang talking sendirian di kamar kosong
- Ganti lokasi atau waktu antara adegan yang berurutan; jangan memakai ruangan yang sama berulang kali
- Narasi panjang dipecah menjadi beberapa adegan pendek
- Pastikan setiap adegan memiliki titik balik emosi yang jelas
- Jaga konsistensi gaya bahasa tiap karakter
- Nomor adegan bertambah berurutan (S01, S02, S03...)
- Rentang waktu harus spesifik (senja, tengah malam, fajar pagi), jangan menulis "siang" secara umum
