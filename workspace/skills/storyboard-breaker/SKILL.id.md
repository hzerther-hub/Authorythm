---
name: storyboard-breaker
description: Standar profesional pemecahan storyboard — memecah skenario menjadi segmen storyboard yang mampu memuat beberapa sub-shot
---

# Panduan Pemecahan Storyboard

## Definisi Inti: Segmen Storyboard

Satu storyboard ＝ satu **segmen storyboard** (segment) ＝ satu tugas pembuatan video.

- Setiap segmen berdurasi **8-15 detik**, di dalamnya memuat **2-4 sub-shot**
- Antar sub-shot **diperbolehkan ganti shot**: ganti ukuran shot, ganti sudut, ganti objek bidikan, disambung dengan hard cut
- Antar sub-shot **tidak berpindah adegan**: satu segmen hanya berlangsung di satu adegan (`scene_id` adalah ikatan level segmen)
- Setiap sub-shot 2-6 detik, terfokus pada satu unit gambar (satu aksi, satu reaksi, satu close-up)

## Alur Pemecahan (Empat Langkah)

2. **Identifikasi beat**: kenali lebih dulu beat naratif skenario — penanda seperti 【Pembuka】【Pemicu】【Klimaks】【Penutup】 dalam skenario, atau titik balik naratif (perpindahan lokasi, pengungkapan aturan, ledakan emosi, plot twist). **Batas beat memaksa pemotongan segmen**, sub-shot di dalam beat yang sama diprioritaskan masuk segmen yang sama, jangan memecah satu rantai sebab-akibat (pembangunan-terjadi-reaksi) ke segmen-segmen berbeda
3. **Penjangkaran total volume**: total durasi target ＝ jumlah karakter skenario ÷ 500 karakter/menit; jumlah segmen ≈ total durasi target ÷ 12 detik, boleh berfluktuasi ±20%. Jangan melebihi atau kurang secara mencolok

## Durasi Berlapis Ritme

Tentukan durasi berdasarkan fungsi segmen, jangan memakai satu ukuran untuk semuanya:

| Tipe segmen | Durasi | Keterangan |
|---|---|---|
| Segmen transisi | 8-10 detik | Perjalanan, empty shot, pembangunan lingkungan, transisi |
| Segmen naratif | 10-15 detik | Kemajuan alur cerita biasa, dialog |
| Segmen titik ledak | 12-15 detik | Close-up, pengungkapan aturan, ledakan emosi, plot twist; ritme sub-shot diperlambat, satu sub-shot boleh bertahan 4-6 detik |

## Batas Bawah Durasi Dialog (Aturan Mutlak)

**Durasi segmen ≥ jumlah total karakter dialog dan narasi di dalam segmen (bagian yang ditulis dalam description) ÷ 4.5 karakter/detik ＋ 2 detik ruang akting**

Dialog yang tidak muat wajib dipindah ke segmen berikutnya, tidak diperbolehkan memadatkan dialog yang tak selesai diaktingkan ke dalam satu segmen.

## Elemen Shot

1. **Judul shot**: ringkasan 3-5 kata atas isi inti segmen (misalnya "Terbangun dari Mimpi Buruk")
2. **Waktu**: jam spesifik ＋ deskripsi cahaya
3. **Lokasi**: deskripsi lengkap latar ＋ tata ruang ＋ detail lingkungan
4. **Ukuran shot**: ukuran shot dominan di dalam segmen; segmen multi-ukuran ditulis kombinasinya, misalnya "medium shot＋close-up"
5. **Sudut**: setara mata/mendongak/menunduk/samping/belakang
6. **Gerakan kamera** `movement`: setiap sub-shot harus memiliki gerakan kamera, dipilih dari kamus dan dituliskan (sub-shot berbeda dalam satu segmen boleh berbeda). Kamus: statis dengan mikro-gerak (denyut seperti napas)/push-in perlahan/pull-back/tracking menyamping/crane naik-turun/orbit melengkung/goyangan handheld/sudut mengintip/fokus tatapan/gemetar/orbit lembut/kejaran kilat/weave pertarungan/menukik dari udara/low-angle ekstrem/kemiringan Dutch angle/over-the-shoulder dekat/sudut pandang orang pertama/whip pan kilat/transisi oklusi/rem mendadak freeze frame/bullet time. Pilih berdasarkan tipe segmen: segmen pembangunan→pull-back yang mengungkap, crane naik-turun, tracking menyamping; segmen dialog→over-the-shoulder dekat, push-in perlahan, denyut napas; segmen emosi→push-in perlahan bergaya denyut jantung, goyangan handheld, gemetar; segmen aksi→untuk pertarungan/aksi kecepatan tinggi utamakan memilih rumus posisi kamera dari skill fight-cinematography, sisanya memakai kejaran kilat, weave pertarungan, tracking menyamping; segmen titik ledak→bullet time, rem mendadak freeze frame, fokus tatapan; suspense thriller→sudut mengintip, Dutch angle, sudut pandang orang pertama. Trik aksen (bullet time/slow motion/fisheye) maksimal 1-2 kali per episode
7. **Deskripsi gambar** `description`: deskripsikan per sub-shot dengan pola `【镜头1】…【镜头2】…` apa yang benar-benar dilihat dan didengar penonton — cara shot difilmkan (gerakan kamera, misalnya "kamera push-in perlahan berkecepatan stabil dari medium shot hingga close-up") ditulis di awal sub-shot tersebut, gambar (siapa ＋ aksi konkret ＋ detail gerak tubuh ＋ ekspresi) ditulis setelah gerakan kamera; bila sub-shot tersebut memiliki dialog, tulis dengan format 「nama karakter berkata: "kalimat"」 di dalam `【镜头N】` terkait, narasi ditulis 「Narasi: isi」
8. **Hasil gambar** `result`: konsekuensi langsung di akhir segmen ＋ detail visual
9. **Suasana** `atmosphere`: cahaya ＋ corak warna ＋ suara ＋ suasana keseluruhan
10. **Durasi** `duration`: total durasi segmen 8-15 detik, dan memenuhi batas bawah durasi dialog
11. **Ikatan latar**: bila dapat mencocokkan dengan latar yang sudah ada, `scene_id` wajib diisi
12. **Ikatan karakter**: isi `character_ids`, ikatkan 0 hingga beberapa karakter yang terlibat di segmen saat ini
13. **Ikatan prop**: isi `prop_ids`, ikatkan 0 hingga beberapa prop kunci yang muncul di segmen saat ini

## Aturan Ikatan Latar

- Bila `location ＋ time` dapat dicocokkan dengan jelas, `scene_id` yang benar wajib diisi mundur
- Jangan mengarang ID latar yang tidak ada
- Bila isi skenario jelas-jelas berlangsung di dalam latar yang sudah ada, jangan menciptakan lagi deskripsi latar baru

## Aturan Ikatan Karakter

- Satu segmen boleh tanpa karakter, juga boleh mengikat beberapa karakter
- Selama ada karakter yang tampil jelas, terlihat, melakukan aksi, atau berbicara di dalam segmen, semua harus diikatkan
- Segmen murni lingkungan, empty shot, close-up benda boleh mengirim array kosong

## Aturan Ikatan Prop

- Bila prop dipakai karakter, diserahkan, mendapat close-up, atau tampak jelas di frame dan bermakna bagi narasi, wajib diikatkan ke segmen tersebut
- Segmen close-up prop (tanpa karakter) juga harus mengikat prop-nya, `character_ids` boleh kosong
- Benda latar yang tidak berkaitan dengan cerita dan tata letak adegan jangan diikat; segmen tanpa kemunculan prop kirim array kosong
- Prop yang diikat akan menjadi gambar referensi pembuatan video (gambar produk berlatar putih), menjamin penampilan prop konsisten lintas segmen

## Persyaratan Kualitas

- `description` harus mudah dibaca manusia, mendeskripsikan secara detail per sub-shot apa yang benar-benar dilihat dan didengar penonton; dialog/narasi ditulis langsung di dalam `【镜头N】` terkait
- `image_prompt` harus menonjolkan komposisi satu frame, penampilan karakter, lingkungan, dan cahaya (mengacu pada sub-shot pertama segmen)
- `bgm_prompt` dan `sound_effect` cukup dengan frasa singkat, tetapi tidak boleh kosong hingga hanya "tegang""sedih"
- Bila perlu penyesuaian, panggil `update_storyboard` untuk mengubah segmen yang spesifik

## Naturalitas dan Kewajaran Identitas (Aturan Mutlak)

- `description` / `result` harus berupa bahasa narasi gambar yang natural: hanya menulis apa yang dilihat dan didengar penonton, dilarang nada analitis dan daftar berpoin (gaya karangan eksposisi 「pertama/kedua」「1、2、3」); penomoran `【镜头N】` adalah satu-satunya penanda struktur yang diperbolehkan
- Perilaku tokoh harus sesuai identitas, usia, dan kemampuan: orang buta huruf tidak bisa membaca tulisan, tidak boleh muncul aksi menulis, membaca surat, melafalkan teks; balita yang terlalu kecil juga tidak boleh muncul logika menulis; karakter yang tidak bisa bahasa asing tidak muncul membaca-menulis bahasa asing. Satu-satunya pengecualian adalah bila teks asli skenario secara eksplisit menuliskan aksi itu — bila skenario tidak menulis, jangan menambahkannya sendiri
- Bila tidak ada dasar kemampuan profesional seperti melek huruf/berhitung, ungkapkan emosi dan informasi lewat aksi, ekspresi, prop, dan sebagainya, jangan jatuh pada 「menulis/membaca tulisan」
