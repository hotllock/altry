package com.altry.app

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.media.MediaPlayer
import android.media.MediaRecorder
import android.net.Uri
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import kotlinx.coroutines.delay
import java.io.File

private const val READING_TEXT =
    "Merhaba, bu benim sesim. Şu anda sesimin kopyalanabilmesi için kısa bir metin okuyorum. " +
        "Sakin, net ve doğal bir tonda konuşmaya çalışıyorum. Bugün hava çok güzel; " +
        "birazdan dışarı çıkıp uzun bir yürüyüş yapmayı düşünüyorum. Peki sen bugün neler yapacaksın?"

/** What the "add voice" dialog is being asked to add. */
private sealed interface Pending {
    data class FromFile(val uri: Uri) : Pending
    data object FromUrl : Pending
}

private fun newRecorder(context: Context, output: File): MediaRecorder {
    @Suppress("DEPRECATION")
    val recorder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) MediaRecorder(context) else MediaRecorder()
    return recorder.apply {
        setAudioSource(MediaRecorder.AudioSource.MIC)
        setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
        setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
        setAudioSamplingRate(44100)
        setAudioEncodingBitRate(128_000)
        setOutputFile(output.absolutePath)
        prepare()
        start()
    }
}

@Composable
fun VoicesScreen(model: AppModel) {
    val context = LocalContext.current
    var pending by remember { mutableStateOf<Pending?>(null) }
    var recorder by remember { mutableStateOf<MediaRecorder?>(null) }
    var seconds by remember { mutableIntStateOf(0) }
    val player = remember { MediaPlayer() }
    val recording = remember { File(context.cacheDir, "kayit.m4a") }

    DisposableEffect(Unit) {
        onDispose {
            player.release()
            recorder?.runCatching { stop() }
            recorder?.release()
        }
    }
    LaunchedEffect(recorder) {
        seconds = 0
        while (recorder != null) {
            delay(1000)
            seconds++
        }
    }

    fun startRecording() {
        runCatching { newRecorder(context, recording) }
            .onSuccess { recorder = it }
            .onFailure { model.message = "Mikrofon açılamadı" }
    }

    fun stopRecording() {
        val active = recorder ?: return
        val ok = runCatching { active.stop() }.isSuccess
        active.release()
        recorder = null
        if (ok && seconds >= 3) pending = Pending.FromFile(Uri.fromFile(recording))
        else model.message = "Kayıt çok kısa, en az 10 saniye konuş"
    }

    val askMicrophone = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) startRecording() else model.message = "Ses kaydı için mikrofon izni gerekli"
    }
    val pickFile = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) pending = Pending.FromFile(uri)
    }

    fun play(voice: Voice) {
        runCatching {
            player.reset()
            player.setDataSource(context, Uri.parse(model.api.sampleUrl(voice.id)), model.api.authHeaders)
            player.setOnPreparedListener { it.start() }
            player.prepareAsync()
        }.onFailure { model.message = "Ses çalınamadı" }
    }

    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item {
            Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer)) {
                Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Kendi sesini klonla", style = MaterialTheme.typography.titleMedium)
                    if (recorder == null) {
                        Text("Sessiz bir yerde 10–20 saniye konuşman yeterli.")
                        Button(onClick = {
                            val granted = ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) ==
                                PackageManager.PERMISSION_GRANTED
                            if (granted) startRecording() else askMicrophone.launch(Manifest.permission.RECORD_AUDIO)
                        }) { Text("Kaydı başlat") }
                    } else {
                        Text("Şu metni oku:", style = MaterialTheme.typography.labelLarge)
                        Text(READING_TEXT)
                        Button(onClick = { stopRecording() }) { Text("Kaydı bitir · $seconds sn") }
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedButton(onClick = { pickFile.launch(arrayOf("audio/*", "video/*")) }) { Text("Dosyadan ekle") }
                        OutlinedButton(onClick = { pending = Pending.FromUrl }) { Text("İnternetten ekle") }
                    }
                }
            }
        }
        item { Text("Seslerim", style = MaterialTheme.typography.titleMedium) }
        if (model.voices.isEmpty()) item {
            Text("Henüz ses eklenmedi.", color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        items(model.voices, key = { "v" + it.id }) { voice ->
            Card(Modifier.fillMaxWidth()) {
                Row(Modifier.padding(start = 16.dp, end = 4.dp, top = 6.dp, bottom = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text(voice.name)
                        Text("${voice.duration.toInt()} sn örnek", style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    IconButton(onClick = { play(voice) }) { Icon(Icons.Filled.PlayArrow, contentDescription = "Dinle") }
                    IconButton(onClick = { model.deleteVoice(voice) }) { Icon(Icons.Filled.Delete, contentDescription = "Sil") }
                }
            }
        }
        val available = model.catalog.filter { !it.installed }
        if (available.isNotEmpty()) {
            item { Text("Hazır sesler", style = MaterialTheme.typography.titleMedium) }
            items(available, key = { "c" + it.id }) { item ->
                Card(Modifier.fillMaxWidth()) {
                    Row(Modifier.padding(start = 16.dp, end = 8.dp, top = 6.dp, bottom = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text(item.name)
                            Text("${item.credit} · ${item.license}", style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                        TextButton(onClick = { model.installCatalogVoice(item) }, enabled = model.busy == null) { Text("Ekle") }
                    }
                }
            }
        }
    }

    pending?.let { request ->
        var name by remember(request) { mutableStateOf("") }
        var url by remember(request) { mutableStateOf("") }
        var consent by remember(request) { mutableStateOf(false) }
        val ready = name.isNotBlank() && consent && (request !is Pending.FromUrl || url.isNotBlank())
        AlertDialog(
            onDismissRequest = { pending = null },
            title = { Text("Ses ekle") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    OutlinedTextField(name, { name = it }, label = { Text("Sesin adı") }, singleLine = true)
                    if (request is Pending.FromUrl) {
                        OutlinedTextField(url, { url = it }, label = { Text("Ses dosyasının bağlantısı") },
                            placeholder = { Text("https://…/ses.mp3") }, singleLine = true)
                    }
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Checkbox(consent, { consent = it })
                        Text("Bu ses bana ait ya da sahibinin kopyalanmasına izni var.",
                            style = MaterialTheme.typography.bodySmall)
                    }
                }
            },
            confirmButton = {
                TextButton(enabled = ready, onClick = {
                    when (request) {
                        is Pending.FromFile -> model.addVoice(name.trim(), request.uri)
                        Pending.FromUrl -> model.addVoiceFromUrl(name.trim(), url.trim())
                    }
                    pending = null
                }) { Text("Ekle") }
            },
            dismissButton = { TextButton(onClick = { pending = null }) { Text("Vazgeç") } },
        )
    }
}
