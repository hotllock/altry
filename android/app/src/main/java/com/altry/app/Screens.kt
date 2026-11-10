package com.altry.app

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.MenuAnchorType
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp

// ---------------------------------------------------------------- shared pieces

@Composable
fun FormColumn(content: @Composable ColumnScope.() -> Unit) = Column(
    Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
    verticalArrangement = Arrangement.spacedBy(14.dp),
    content = content,
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun Picker(label: String, options: List<Pair<String, String>>, selected: String, onSelect: (String) -> Unit) {
    var expanded by remember { mutableStateOf(false) }
    ExposedDropdownMenuBox(expanded, onExpandedChange = { expanded = it }) {
        OutlinedTextField(
            value = options.firstOrNull { it.first == selected }?.second ?: "Seçin",
            onValueChange = {},
            readOnly = true,
            singleLine = true,
            label = { Text(label) },
            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded) },
            modifier = Modifier.menuAnchor(MenuAnchorType.PrimaryNotEditable).fillMaxWidth(),
        )
        ExposedDropdownMenu(expanded, onDismissRequest = { expanded = false }) {
            options.forEach { (value, text) ->
                DropdownMenuItem(text = { Text(text) }, onClick = { onSelect(value); expanded = false })
            }
        }
    }
}

@Composable
fun SwitchRow(title: String, hint: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f).padding(end = 12.dp)) {
            Text(title, style = MaterialTheme.typography.bodyLarge)
            Text(hint, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Switch(checked, onChange)
    }
}

// A "pick a file" row. `mime` lists the accepted MIME types separated with a pipe character.
@Composable
fun FilePick(label: String, mime: String, uri: Uri?, onPicked: (Uri?) -> Unit) {
    val resolver = LocalContext.current.contentResolver
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { picked ->
        if (picked != null) onPicked(picked)
    }
    Card(Modifier.fillMaxWidth().clickable { launcher.launch(mime.split("|").toTypedArray()) }) {
        Row(Modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(label, style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.primary)
                Text(
                    if (uri == null) "Seçmek için dokun" else remember(uri) { nameOf(resolver, uri) },
                    maxLines = 1, overflow = TextOverflow.Ellipsis,
                )
            }
            if (uri != null) TextButton(onClick = { onPicked(null) }) { Text("Kaldır") }
        }
    }
}

@Composable
fun LanguagePicker(model: AppModel, label: String, selected: String, onSelect: (String) -> Unit) =
    Picker(label, model.languages.map { it.code to it.name }, selected, onSelect)

/** Library voice dropdown. Shows a shortcut to the Voices tab when the library is empty. */
@Composable
fun VoicePicker(model: AppModel, selected: String, onSelect: (String) -> Unit, onAddVoice: () -> Unit) {
    if (model.voices.isEmpty()) {
        Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer)) {
            Column(Modifier.padding(16.dp)) {
                Text("Henüz kayıtlı ses yok. Kendi sesini kaydet ya da hazır seslerden birini ekle.")
                TextButton(onClick = onAddVoice) { Text("Ses ekle") }
            }
        }
    } else {
        Picker("Ses", model.voices.map { it.id to it.name }, selected, onSelect)
    }
}

@Composable
fun StartButton(text: String, enabled: Boolean, model: AppModel, onClick: () -> Unit) {
    Button(onClick, enabled = enabled && model.busy == null, modifier = Modifier.fillMaxWidth().height(52.dp)) {
        Text(text)
    }
}

// ---------------------------------------------------------------- studio

@Composable
fun StudioHome(model: AppModel, onOpen: (Tool) -> Unit, onSettings: () -> Unit) {
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), Arrangement.spacedBy(12.dp)) {
        if (model.health == null) {
            Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.errorContainer)) {
                Column(Modifier.padding(16.dp)) {
                    Text(model.connectionError ?: "Sunucuya bağlı değil", color = MaterialTheme.colorScheme.onErrorContainer)
                    Row {
                        TextButton(onClick = onSettings) { Text("Ayarlar") }
                        TextButton(onClick = { model.connect() }) { Text("Yeniden dene") }
                    }
                }
            }
        }
        Tool.entries.forEach { tool ->
            Card(Modifier.fillMaxWidth().clickable { onOpen(tool) }) {
                Column(Modifier.padding(18.dp)) {
                    Text(tool.title, style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(4.dp))
                    Text(tool.description, style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }
    }
}

@Composable
fun DubScreen(model: AppModel, onStarted: () -> Unit) {
    var video by rememberSaveable { mutableStateOf<Uri?>(null) }
    var target by rememberSaveable { mutableStateOf("tr") }
    var source by rememberSaveable { mutableStateOf("") }
    var voice by rememberSaveable { mutableStateOf(ORIGINAL_VOICE) }
    var background by rememberSaveable { mutableStateOf(true) }
    var subtitles by rememberSaveable { mutableStateOf(false) }
    FormColumn {
        FilePick("Video ya da ses dosyası", "video/*|audio/*", video) { video = it }
        LanguagePicker(model, "Hangi dile çevrilsin?", target) { target = it }
        Picker("Videonun dili", listOf("" to "Otomatik algıla") + model.languages.map { it.code to it.name }, source) { source = it }
        Picker(
            "Dublaj sesi",
            listOf(ORIGINAL_VOICE to "Videodaki konuşmacının kendi sesi") + model.voices.map { it.id to it.name },
            voice,
        ) { voice = it }
        SwitchRow("Arka plan sesini koru", "Müzik ve efektler dublajın altında kalır", background) { background = it }
        SwitchRow("Altyazı ekle", "Çeviriyi açılıp kapatılabilen altyazı olarak videoya gömer", subtitles) { subtitles = it }
        StartButton("Dublajı başlat", video != null, model) {
            model.startJob(
                "dub",
                mapOf("target_lang" to target, "source_lang" to source, "voice_id" to voice,
                    "keep_background" to "$background", "subtitles" to "$subtitles"),
                listOf(Upload("file", video!!)), onStarted,
            )
        }
    }
}

@Composable
fun VoiceChangeScreen(model: AppModel, onStarted: () -> Unit, onAddVoice: () -> Unit) {
    var media by rememberSaveable { mutableStateOf<Uri?>(null) }
    var voice by rememberSaveable { mutableStateOf(model.voices.firstOrNull()?.id ?: "") }
    var background by rememberSaveable { mutableStateOf(true) }
    FormColumn {
        FilePick("Video ya da ses dosyası", "video/*|audio/*", media) { media = it }
        VoicePicker(model, voice, { voice = it }, onAddVoice)
        SwitchRow("Arka plan sesini koru", "Sunucuda ses ayırma kuruluysa müzik ve efektler korunur", background) { background = it }
        Text("Söylenen sözler ve zamanlama aynı kalır, yalnızca konuşanın sesi değişir.",
            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        StartButton("Sesi değiştir", media != null && voice.isNotEmpty(), model) {
            model.startJob("voice-change", mapOf("voice_id" to voice, "keep_background" to "$background"),
                listOf(Upload("file", media!!)), onStarted)
        }
    }
}

@Composable
fun SpeakScreen(model: AppModel, onStarted: () -> Unit, onAddVoice: () -> Unit) {
    var text by rememberSaveable { mutableStateOf("") }
    var language by rememberSaveable { mutableStateOf("tr") }
    var voice by rememberSaveable { mutableStateOf(model.voices.firstOrNull()?.id ?: "") }
    var video by rememberSaveable { mutableStateOf<Uri?>(null) }
    var originalVolume by rememberSaveable { mutableStateOf(0f) }
    FormColumn {
        OutlinedTextField(text, { text = it }, label = { Text("Söylenecek metin") },
            modifier = Modifier.fillMaxWidth().heightIn(min = 140.dp))
        LanguagePicker(model, "Metnin dili", language) { language = it }
        VoicePicker(model, voice, { voice = it }, onAddVoice)
        FilePick("Videoya ekle (isteğe bağlı)", "video/*", video) { video = it }
        if (video != null) {
            Text("Videonun kendi sesi: %${(originalVolume * 100).toInt()}", style = MaterialTheme.typography.bodyMedium)
            Slider(originalVolume, { originalVolume = it })
        }
        StartButton(if (video == null) "Seslendir" else "Seslendir ve videoya koy",
            text.isNotBlank() && voice.isNotEmpty(), model) {
            model.startJob(
                "speak",
                mapOf("text" to text, "language" to language, "voice_id" to voice, "original_volume" to "$originalVolume"),
                listOfNotNull(video?.let { Upload("file", it) }), onStarted,
            )
        }
    }
}

@Composable
fun CreateVideoScreen(model: AppModel, onStarted: () -> Unit, onAddVoice: () -> Unit) {
    var script by rememberSaveable { mutableStateOf("") }
    var language by rememberSaveable { mutableStateOf("tr") }
    var voice by rememberSaveable { mutableStateOf(model.voices.firstOrNull()?.id ?: "") }
    var aspect by rememberSaveable { mutableStateOf("9:16") }
    var subtitles by rememberSaveable { mutableStateOf(true) }
    var images by remember { mutableStateOf(listOf<Uri>()) }
    var autoImages by rememberSaveable { mutableStateOf(true) }
    var imageQuery by rememberSaveable { mutableStateOf("") }
    var music by rememberSaveable { mutableStateOf<Uri?>(null) }
    val pickImages = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { images = it }
    FormColumn {
        OutlinedTextField(script, { script = it }, label = { Text("Video metni") },
            supportingText = { Text("Her satır ya da cümle ayrı bir sahne olur") },
            modifier = Modifier.fillMaxWidth().heightIn(min = 160.dp))
        LanguagePicker(model, "Metnin dili", language) { language = it }
        VoicePicker(model, voice, { voice = it }, onAddVoice)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf("9:16" to "Dikey", "16:9" to "Yatay", "1:1" to "Kare").forEach { (value, label) ->
                FilterChip(aspect == value, onClick = { aspect = value }, label = { Text("$label $value") })
            }
        }
        Card(Modifier.fillMaxWidth().clickable { pickImages.launch(arrayOf("image/*")) }) {
            Row(Modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("Görseller (isteğe bağlı)", style = MaterialTheme.typography.labelLarge,
                        color = MaterialTheme.colorScheme.primary)
                    Text(if (images.isEmpty()) "Kendi görsellerini seçebilirsin" else "${images.size} görsel seçildi")
                }
                if (images.isNotEmpty()) TextButton(onClick = { images = emptyList() }) { Text("Kaldır") }
            }
        }
        if (images.isEmpty()) {
            SwitchRow("İnternetten görsel bul", "Her sahneye uygun, serbest lisanslı bir fotoğraf arka plan olur; " +
                "kapalıysa renkli arka planlar kullanılır", autoImages) { autoImages = it }
            if (autoImages) {
                OutlinedTextField(imageQuery, { imageQuery = it }, label = { Text("Görsel konusu (isteğe bağlı)") },
                    supportingText = { Text("Örn. İstanbul, uzay, orman. Boş bırakılırsa her sahnenin kendi metnine göre aranır") },
                    singleLine = true, modifier = Modifier.fillMaxWidth())
            }
        }
        FilePick("Fon müziği (isteğe bağlı)", "audio/*", music) { music = it }
        SwitchRow("Altyazı", "Söylenen metin videonun üzerine yazılır", subtitles) { subtitles = it }
        StartButton("Videoyu üret", script.isNotBlank() && voice.isNotEmpty(), model) {
            model.startJob(
                "create-video",
                mapOf("script" to script, "language" to language, "voice_id" to voice, "aspect" to aspect,
                    "subtitles" to "$subtitles", "auto_images" to "${autoImages && images.isEmpty()}",
                    "image_query" to imageQuery.trim()),
                images.map { Upload("images", it) } + listOfNotNull(music?.let { Upload("music", it) }), onStarted,
            )
        }
    }
}

// ---------------------------------------------------------------- jobs

private val jobNames = mapOf("dub" to "Dublaj", "voice-change" to "Ses değiştirme", "speak" to "Seslendirme",
    "narrate" to "Videoya seslendirme", "create-video" to "Video üretimi")

@Composable
fun JobsScreen(model: AppModel) {
    if (model.jobs.isEmpty()) {
        Column(Modifier.fillMaxSize().padding(32.dp), Arrangement.Center, Alignment.CenterHorizontally) {
            Text("Henüz iş yok. Stüdyo'dan bir işlem başlat.", color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        return
    }
    LazyColumn(Modifier.fillMaxSize(), contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)) {
        items(model.jobs, key = { it.id }) { job ->
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text(jobNames[job.type] ?: job.type, style = MaterialTheme.typography.labelLarge,
                        color = MaterialTheme.colorScheme.primary)
                    Text(job.title, maxLines = 2, overflow = TextOverflow.Ellipsis)
                    when (job.status) {
                        "queued", "running" -> {
                            LinearProgressIndicator(progress = { job.progress }, Modifier.fillMaxWidth())
                            Text("${job.stage} · %${(job.progress * 100).toInt()}", style = MaterialTheme.typography.bodySmall)
                            TextButton(onClick = { model.deleteJob(job) }) { Text("İptal et") }
                        }
                        "done" -> Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                            Button(onClick = { model.openResult(job, share = false) }) { Text("Aç") }
                            if (model.canSaveToGallery) OutlinedButton(onClick = { model.saveResult(job) }) { Text("Kaydet") }
                            OutlinedButton(onClick = { model.openResult(job, share = true) }) { Text("Paylaş") }
                            TextButton(onClick = { model.deleteJob(job) }) { Text("Sil") }
                        }
                        else -> {
                            Text(if (job.status == "cancelled") "İptal edildi" else "Hata: ${job.error ?: "bilinmiyor"}",
                                color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
                            TextButton(onClick = { model.deleteJob(job) }) { Text("Sil") }
                        }
                    }
                }
            }
        }
    }
}

// ---------------------------------------------------------------- settings

@Composable
fun SettingsScreen(model: AppModel) {
    var url by rememberSaveable { mutableStateOf(model.settings.serverUrl) }
    var token by rememberSaveable { mutableStateOf(model.settings.token) }
    FormColumn {
        Text("Altry'nin yapay zekâ motoru senin sunucunda çalışır: kendi bilgisayarında ya da ücretsiz " +
            "Google Colab'da. Sunucuyu başlattığında sana verilen adresi buraya yaz.",
            style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        OutlinedTextField(url, { url = it }, label = { Text("Sunucu adresi") }, singleLine = true,
            placeholder = { Text("http://192.168.1.20:8000") },
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri), modifier = Modifier.fillMaxWidth())
        OutlinedTextField(token, { token = it }, label = { Text("Erişim anahtarı (varsa)") }, singleLine = true,
            modifier = Modifier.fillMaxWidth())
        StartButton("Kaydet ve bağlan", url.isNotBlank(), model) { model.saveSettings(url, token) }
        val health = model.health
        when {
            health != null -> Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer)) {
                Column(Modifier.fillMaxWidth().padding(16.dp)) {
                    Text("Bağlandı · sürüm ${health.version}", style = MaterialTheme.typography.titleSmall)
                    Text(when (health.device) {
                        "cuda" -> "Ekran kartı (GPU) kullanılıyor: hızlı"
                        "fake" -> "Deneme modu: gerçek modeller kapalı"
                        else -> "İşlemci (CPU) kullanılıyor: işlemler yavaş olur"
                    })
                    Text(if (health.separation) "Arka plan sesi ayırma: açık" else "Arka plan sesi ayırma: kurulu değil")
                }
            }
            model.connectionError != null -> Text(model.connectionError!!, color = MaterialTheme.colorScheme.error)
        }
    }
}
