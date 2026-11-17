package vn.pp.photos

import android.app.Activity
import android.content.Context
import android.graphics.Bitmap
import android.os.Bundle
import androidx.fragment.app.FragmentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.IntentSenderRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.tween
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.foundation.gestures.detectVerticalDragGestures
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.rememberLazyGridState
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.platform.LocalDensity
import kotlinx.coroutines.delay
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.gestures.calculateCentroid
import androidx.compose.material3.Checkbox
import androidx.compose.ui.unit.IntSize
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.calculatePan
import androidx.compose.foundation.gestures.calculateZoom
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.runtime.snapshotFlow
import kotlinx.coroutines.flow.collectLatest
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.foundation.layout.requiredWidth
import androidx.compose.foundation.layout.requiredHeight
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.sp
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.foundation.gestures.detectDragGesturesAfterLongPress
import androidx.compose.ui.input.pointer.positionChanged
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import com.google.android.gms.auth.api.identity.AuthorizationRequest
import com.google.android.gms.auth.api.identity.Identity
import com.google.android.gms.common.api.Scope
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.launch

class MainActivity : FragmentActivity() {
    private var pending: CompletableDeferred<String?>? = null
    private lateinit var launcher: androidx.activity.result.ActivityResultLauncher<IntentSenderRequest>

    /** Xin token Drive. Lần đầu Google hiện màn hình đồng ý; các lần sau lấy thẳng. */
    suspend fun fetchToken(): String? {
        val d = CompletableDeferred<String?>()
        pending = d
        val req = AuthorizationRequest.builder().setRequestedScopes(listOf(Scope("https://www.googleapis.com/auth/drive"))).build()
        Identity.getAuthorizationClient(this).authorize(req)
            .addOnSuccessListener { r ->
                if (r.hasResolution()) {
                    try {
                        launcher.launch(IntentSenderRequest.Builder(r.pendingIntent!!.intentSender).build())
                    } catch (e: Exception) { d.complete(null) }
                } else d.complete(r.accessToken)
            }
            .addOnFailureListener { e -> lastError = e.message ?: e.toString(); d.complete(null) }
        return d.await()
    }

    var lastError = ""

    // khóa lại khi rời ứng dụng (tắt màn hình, chuyển ứng dụng, vuốt ra khỏi app): quay lại phải xác nhận mở khóa
    var relock by mutableStateOf(false)
    var foreground by mutableStateOf(false)

    override fun onStart() {
        super.onStart()
        foreground = true
    }

    override fun onStop() {
        super.onStop()
        foreground = false
        if (Store.isOpen) relock = true
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // chặn chụp màn hình và ẩn nội dung trong màn hình ứng dụng gần đây
        window.setFlags(android.view.WindowManager.LayoutParams.FLAG_SECURE, android.view.WindowManager.LayoutParams.FLAG_SECURE)
        Store.init(applicationContext)
        launcher = registerForActivityResult(ActivityResultContracts.StartIntentSenderForResult()) { res ->
            try {
                val r = Identity.getAuthorizationClient(this).getAuthorizationResultFromIntent(res.data)
                pending?.complete(r.accessToken)
            } catch (e: Exception) {
                lastError = e.message ?: e.toString()
                pending?.complete(null)
            }
        }
        Drive.refresh = { fetchToken() }
        setContent { PPTheme { Root(this) } }
    }
}

val Brass = Color(0xFFA9793D)

@Composable
fun PPTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = lightColorScheme(primary = Brass, background = Color(0xFFF6F1E6), surface = Color(0xFFFFFBF2)), content = content)
}

@Composable
fun Root(act: MainActivity) {
    val ctx = act.applicationContext
    val prefs = remember { ctx.getSharedPreferences("pp", Context.MODE_PRIVATE) }
    var ready by remember { mutableStateOf(false) }
    var busy by remember { mutableStateOf(false) }
    var msg by remember { mutableStateOf("") }
    var pw by remember { mutableStateOf(prefs.getString("pw", "") ?: "") }
    var enc by remember { mutableStateOf(prefs.getString("pw_enc", null)) }
    var offer by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()
    val canLock = remember { Lock.available(act) }

    fun connect(password: String) {
        busy = true
        msg = "Đang đăng nhập Google…"
        scope.launch {
            try {
                val t = act.fetchToken()
                if (t.isNullOrEmpty()) throw RuntimeException("Chưa đăng nhập được Google. ${act.lastError}")
                Drive.token = t
                Store.open(password) { msg = it }
                if (canLock) {
                    if (enc == null) offer = password           // hỏi có muốn dùng vân tay / khóa màn hình cho lần sau
                } else prefs.edit().putString("pw", password).apply()
                ready = true
            } catch (e: Crypto.WrongPassword) {
                msg = "Mật khẩu đồng bộ không đúng."
            } catch (e: Exception) {
                msg = e.message ?: e.toString()
            } finally {
                busy = false
            }
        }
    }

    fun unlockWithDevice() {
        val stored = enc ?: return
        Lock.authenticate(act, "Mở Private Picture", {
            try {
                val p = Lock.decrypt(stored)
                pw = p
                connect(p)
            } catch (e: Exception) {
                msg = "Không mở nhanh được, hãy nhập mật khẩu đồng bộ. (${e.message})"
                prefs.edit().remove("pw_enc").apply()
                enc = null
            }
        }, { m -> msg = m })
    }
    LaunchedEffect(Unit) { if (enc != null && canLock) unlockWithDevice() }

    offer?.let { password ->
        if (ready) androidx.compose.material3.AlertDialog(
            onDismissRequest = { offer = null },
            title = { Text("Mở nhanh lần sau?") },
            text = { Text("Dùng vân tay hoặc khóa màn hình của điện thoại để mở app, khỏi nhập lại mật khẩu đồng bộ. Mật khẩu được cất trong kho khóa an toàn của Android.") },
            confirmButton = {
                TextButton({
                    offer = null
                    Lock.authenticate(act, "Bật mở nhanh", {
                        try {
                            val s = Lock.encrypt(password)
                            prefs.edit().putString("pw_enc", s).remove("pw").apply()
                            enc = s
                        } catch (e: Exception) { msg = e.message ?: "" }
                    }, { m -> msg = m })
                }) { Text("Bật") }
            },
            dismissButton = { TextButton({ offer = null }) { Text("Để sau") } })
    }

    if (!ready) {
        Column(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background).padding(28.dp), verticalArrangement = Arrangement.Center) {
            Text("Private Picture", style = MaterialTheme.typography.headlineMedium)
            Text("Xem thư viện ảnh của bạn qua Google Drive. Dữ liệu được mã hóa bằng mật khẩu đồng bộ, chỉ máy này giải mã.", Modifier.padding(vertical = 12.dp))
            OutlinedTextField(pw, { pw = it }, label = { Text("Mật khẩu đồng bộ") }, visualTransformation = PasswordVisualTransformation(), singleLine = true, modifier = Modifier.fillMaxWidth())
            if (enc != null && canLock) Button({ unlockWithDevice() }, enabled = !busy, modifier = Modifier.padding(top = 16.dp)) { Text("Mở bằng vân tay / khóa màn hình") }
            Button({ connect(pw) }, enabled = !busy && pw.isNotEmpty(), modifier = Modifier.padding(top = 12.dp)) { Text("Đăng nhập Google và mở") }
            if (busy) CircularProgressIndicator(Modifier.padding(top = 16.dp))
            if (msg.isNotEmpty()) Text(msg, Modifier.padding(top = 12.dp), color = if (busy) Color.Gray else Color(0xFFB03A2E))
        }
        return
    }
    Box(Modifier.fillMaxSize()) {
        Main()
        if (act.relock) LockScreen(act, canLock) { act.relock = false }
    }
}

/** Màn hình khóa phủ kín khi quay lại app: dùng vân tay hoặc khóa màn hình của điện thoại, hoặc nhập lại mật khẩu đồng bộ. */
@Composable
fun LockScreen(act: MainActivity, canLock: Boolean, onUnlock: () -> Unit) {
    var msg by remember { mutableStateOf("") }
    var pw by remember { mutableStateOf("") }
    var usePw by remember { mutableStateOf(!canLock) }
    BackHandler(true) { }
    fun prompt() {
        if (!canLock) return
        Lock.authenticate(act, "Mở khóa Private Picture", { onUnlock() }, { m -> msg = m })
    }
    LaunchedEffect(act.foreground) { if (act.foreground && canLock && !usePw) prompt() }
    Column(Modifier.fillMaxSize().background(Color(0xFF16130F)).padding(28.dp), verticalArrangement = Arrangement.Center, horizontalAlignment = Alignment.CenterHorizontally) {
        Text("Private Picture", style = MaterialTheme.typography.headlineMedium, color = Color(0xFFF6F1E6))
        Text("Đã khóa để bảo vệ ảnh của bạn.", Modifier.padding(vertical = 12.dp), color = Color(0xFFC9A66B))
        if (usePw) {
            OutlinedTextField(pw, { pw = it; msg = "" }, label = { Text("Mật khẩu đồng bộ") }, visualTransformation = PasswordVisualTransformation(), singleLine = true, modifier = Modifier.fillMaxWidth())
            Button({ if (Store.checkPassword(pw)) onUnlock() else msg = "Mật khẩu không đúng." }, enabled = pw.isNotEmpty(), modifier = Modifier.padding(top = 16.dp)) { Text("Mở khóa") }
        } else {
            Button({ prompt() }, modifier = Modifier.padding(top = 8.dp)) { Text("Mở khóa bằng vân tay / khóa màn hình") }
            if (Store.isOpen) TextButton({ usePw = true }) { Text("Nhập mật khẩu đồng bộ", color = Color(0xFFC9A66B)) }
        }
        if (msg.isNotEmpty()) Text(msg, Modifier.padding(top = 12.dp), color = Color(0xFFE57373))
    }
}

sealed class Screen {
    object Tabs : Screen()
    class PersonView(val p: Person) : Screen()
    class LabelView(val l: Label) : Screen()
    class Suggest(val p: Person) : Screen()                         // trang đề xuất: ảnh chưa chắc chắn là của người này
}

/** Kiểm tra bản app mới (PC đặt vào Drive khi đồng bộ); hỏi rồi tải và mở trình cài đặt của Android. */
@Composable
fun UpdateChecker() {
    val ctx = androidx.compose.ui.platform.LocalContext.current
    var upd by remember { mutableStateOf<AppUpdate?>(null) }
    var busy by remember { mutableStateOf(false) }
    var err by remember { mutableStateOf("") }
    val scope = rememberCoroutineScope()
    LaunchedEffect(Unit) {
        val code = try {
            androidx.core.content.pm.PackageInfoCompat.getLongVersionCode(ctx.packageManager.getPackageInfo(ctx.packageName, 0))
        } catch (e: Exception) { Long.MAX_VALUE }
        upd = Store.checkUpdate(code)
    }
    val u = upd ?: return
    AlertDialog(onDismissRequest = { if (!busy) upd = null }, title = { Text("Có bản mới ${u.version}") },
        text = { Text(if (busy) "Đang tải bản cập nhật…" else if (err.isNotEmpty()) err else "Bản cập nhật đã sẵn sàng trên Drive. Bấm Cập nhật để cài đặt (Android có thể hỏi cho phép cài từ ứng dụng này).") },
        confirmButton = {
            TextButton({
                if (busy) return@TextButton
                busy = true; err = ""
                scope.launch {
                    try {
                        if (!ctx.packageManager.canRequestPackageInstalls()) {
                            ctx.startActivity(android.content.Intent(android.provider.Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                                android.net.Uri.parse("package:" + ctx.packageName)).addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK))
                            err = "Hãy bật “Cho phép từ nguồn này” rồi quay lại và bấm Cập nhật lần nữa."
                        } else {
                            val f = Store.downloadApk(u)
                            val uri = androidx.core.content.FileProvider.getUriForFile(ctx, ctx.packageName + ".files", f)
                            ctx.startActivity(android.content.Intent(android.content.Intent.ACTION_VIEW)
                                .setDataAndType(uri, "application/vnd.android.package-archive")
                                .addFlags(android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION or android.content.Intent.FLAG_ACTIVITY_NEW_TASK))
                        }
                    } catch (e: Exception) { err = "Không cập nhật được: ${e.message}" } finally { busy = false }
                }
            }) { Text("Cập nhật") }
        },
        dismissButton = { TextButton({ if (!busy) upd = null }) { Text("Để sau") } })
}

@Composable
fun Main() {
    UpdateChecker()
    var area by remember { mutableStateOf("settings") }              // mở ở Cài đặt (không có ảnh) để người xung quanh không nhìn thấy ảnh riêng tư; còn "model", "all", "combo", "fav"
    var screen by remember { mutableStateOf<Screen>(Screen.Tabs) }
    var viewer by remember { mutableStateOf<Pair<List<Img>, Int>?>(null) }
    var fromSuggest by remember { mutableStateOf<Person?>(null) }       // đang xem ảnh từ trang đề xuất của người này (nút người − = không phải người này)
    var fromPerson by remember { mutableStateOf<Person?>(null) }        // đang xem ảnh trong nhóm của người này (để có nút loại khỏi danh sách)
    var locateUid by remember { mutableStateOf<String?>(null) }         // ảnh cần cuộn tới trong All
    val scope = rememberCoroutineScope()
    var dlg by remember { mutableStateOf("") }                          // "", "add", "confirmAdd", "create", "confirmCreate", "cloth"
    var pick by remember { mutableStateOf<Person?>(null) }
    var newName by remember { mutableStateOf("") }
    var undo by remember { mutableStateOf<UndoItem?>(null) }
    var note by remember { mutableStateOf("") }
    val holder = androidx.compose.runtime.saveable.rememberSaveableStateHolder()   // mỗi tab nhớ vị trí cuộn riêng: đổi tab rồi quay lại vẫn đúng chỗ cũ
    val open: (List<Img>, Int) -> Unit = { l, i -> viewer = l to i; fromPerson = (screen as? Screen.PersonView)?.p; fromSuggest = (screen as? Screen.Suggest)?.p }
    EdgeBack(viewer != null || screen !is Screen.Tabs) {
        val sc = screen
        if (viewer != null) viewer = null else if (sc is Screen.Suggest) screen = Screen.PersonView(sc.p) else screen = Screen.Tabs
    }
    EdgeBack(Store.selected.isNotEmpty() && viewer == null) { Store.selected = emptySet() }     // vuốt từ cạnh màn hình: bỏ chọn
    // tự nhận dữ liệu mới từ máy tính: khi app đang mở, mỗi 90 giây kiểm tra Drive, PC đã đồng bộ mới thì tải lại ở nền (không cần bấm ↻)
    val lifecycleOwner = androidx.compose.ui.platform.LocalLifecycleOwner.current
    androidx.compose.runtime.DisposableEffect(lifecycleOwner) {                  // mở lại app (hoặc quay lại từ app khác): kiểm tra ngay xem PC có dữ liệu mới không
        val obs = androidx.lifecycle.LifecycleEventObserver { _, ev ->
            if (ev == androidx.lifecycle.Lifecycle.Event.ON_START) scope.launch { try { Store.refreshIfRemoteChanged() } catch (e: Exception) { } }
        }
        lifecycleOwner.lifecycle.addObserver(obs)
        onDispose { lifecycleOwner.lifecycle.removeObserver(obs) }
    }
    LaunchedEffect(Unit) {
        while (true) {
            delay(90_000)
            if (lifecycleOwner.lifecycle.currentState.isAtLeast(androidx.lifecycle.Lifecycle.State.STARTED) && !Store.viewerActive) {
                try { Store.refreshIfRemoteChanged() } catch (e: Exception) { }
            }
        }
    }
    val sel = Store.selected
    val poolUids = remember(Store.pool) { Store.pool.map { it.uid }.toHashSet() }
    val here = remember(sel, poolUids) { sel.filter { it in poolUids } }    // thao tác CHỈ áp dụng cho ảnh đã chọn trong danh sách của tab đang mở (ảnh chọn ở tab khác vẫn giữ nhưng không bị tác động)
    LaunchedEffect(area, screen) { if (screen is Screen.Tabs && area != "all" && area != "combo" && area != "fav") Store.pool = emptyList() }
    fun doClassify(code: String, name: String) {                          // chuyển các ảnh đã chọn trong danh sách đang mở sang Dressed / Naked (có Hoàn tác)
        val ids = here.toList()
        if (ids.isEmpty()) return
        val prev = ids.map { it to Store.clothing[it] }
        scope.launch {
            try { Store.setCloth(ids, code) } catch (e: Exception) { }
            Store.selected = Store.selected - ids.toSet()
            undo = UndoItem("Đã chuyển sang $name", ids) {
                for (c in listOf("cloth", "nude")) { val g = prev.filter { it.second == c }.map { it.first }; if (g.isNotEmpty()) Store.setCloth(g, c) }
                val none = prev.filter { it.second == null }.map { it.first }
                if (none.isNotEmpty()) Store.clearCloth(none)
            }
        }
    }
    val personView = screen is Screen.PersonView
    Box(Modifier.fillMaxSize()) {
        Column(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background)) {
            Box(Modifier.weight(1f).fillMaxWidth()) {
                val v = Store.version
                when (val s = screen) {
                    is Screen.PersonView -> PersonScreen(s.p, open, { c, n -> doClassify(c, n) }, { dlg = "add" }, {
                        val ids = here.toList(); val pp = s.p                                          // Loại khỏi danh sách: các ảnh đã chọn không còn thuộc người này (có Hoàn tác)
                        scope.launch {
                            try { Store.personRemove(pp, ids) } catch (e: Exception) { }
                            Store.selected = Store.selected - ids.toSet()
                            undo = UndoItem("Đã loại khỏi danh sách", ids) { Store.personRestore(pp, ids) }
                        }
                    }, { screen = Screen.Suggest(s.p) }) { screen = Screen.Tabs }
                    is Screen.Suggest -> SuggestScreen(s.p, open,
                        onAccept = {                                                  // dấu tick: đúng người này
                            val ids = here.toList(); val pp = s.p
                            if (ids.isNotEmpty()) scope.launch {
                                try { Store.guessAccept(pp, ids) } catch (e: Exception) { }
                                Store.selected = Store.selected - ids.toSet()
                                undo = UndoItem("Đã xác nhận đúng", ids) { Store.personRemove(pp, ids); Store.guessRestore(pp, ids) }
                            }
                        },
                        onAdd = { dlg = "add" },                                      // người + : thêm vào tên khác
                        onReject = {                                                  // người − : không phải người này
                            val ids = here.toList(); val pp = s.p
                            if (ids.isNotEmpty()) scope.launch {
                                try { Store.guessReject(pp, ids) } catch (e: Exception) { }
                                Store.selected = Store.selected - ids.toSet()
                                undo = UndoItem("Đã loại khỏi đề xuất", ids) { Store.guessRestore(pp, ids) }
                            }
                        },
                        onLocate = { val u = here.firstOrNull(); if (u != null) { Store.selected = emptySet(); screen = Screen.Tabs; area = "all"; locateUid = u } },
                        onClassify = { c, n -> doClassify(c, n) }) { screen = Screen.PersonView(s.p) }
                    is Screen.LabelView -> LabelScreen(s.l, open) { screen = Screen.Tabs }
                    else -> holder.SaveableStateProvider(area) {
                        when (area) {
                            "all" -> AllPhotos(open, locateUid, false, { c, n -> doClassify(c, n) }) { dlg = "add" }
                            "combo" -> ComboScreen(open)
                            "fav" -> androidx.compose.runtime.CompositionLocalProvider(LocalShowStars provides false) { AllPhotos(open, null, true, { c, n -> doClassify(c, n) }) { dlg = "add" } }          // tab Favorite: không cần hiện sao trên từng ảnh
                            "settings" -> SettingsScreen()
                            else -> ModelScreen { screen = Screen.PersonView(it) }
                        }
                    }
                }
                if (v < 0) Text("")
                if (sel.isNotEmpty() && viewer == null && !personView) {   // góc trên: ✕ và số ảnh đã chọn (bấm để bỏ chọn); trang một người có nút ✕ tròn riêng
                    Row(Modifier.align(Alignment.TopStart).padding(8.dp).shadow(4.dp, RoundedCornerShape(24.dp)).background(Color.White, RoundedCornerShape(24.dp))
                        .clickable { Store.selected = emptySet() }.padding(horizontal = 16.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text("✕", color = Color(0xFF1B1812))
                        Text(if (here.size == sel.size) "${sel.size}" else "${here.size} / ${sel.size}", Modifier.padding(start = 10.dp), color = Color(0xFF1B1812), style = MaterialTheme.typography.titleMedium)
                    }
                }
                undo?.let { u ->                                           // vừa thao tác: có nút Hoàn tác phòng bấm nhầm; hoàn tác xong các ảnh vừa chọn được chọn lại
                    LaunchedEffect(u) { kotlinx.coroutines.delay(20000); if (undo === u) undo = null }
                    // một dòng chữ gọn: "Đã xác nhận đúng  Hoàn tác" (không còn hộp to)
                    Row(Modifier.align(Alignment.BottomCenter).padding(bottom = 10.dp).background(Color(0xE62B261E), RoundedCornerShape(14.dp)).padding(horizontal = 12.dp, vertical = 5.dp),
                        verticalAlignment = Alignment.CenterVertically) {
                        Text(u.text, color = Color.White, style = MaterialTheme.typography.bodySmall, maxLines = 1)
                        Text("Hoàn tác", Modifier.clickable { scope.launch { try { u.revert() } catch (e: Exception) { }; undo = null; Store.selected = Store.selected + u.uids } }.padding(start = 12.dp, top = 2.dp, bottom = 2.dp),
                            color = Color(0xFFE5C07B), style = MaterialTheme.typography.bodySmall)
                    }
                }
            }
            if (sel.isNotEmpty() && here.isEmpty() && viewer == null && !personView && screen !is Screen.Suggest) {
                Text("Chưa chọn ảnh nào trong danh sách này (còn ${sel.size} ảnh đã chọn ở tab khác, vẫn được giữ)", Modifier.fillMaxWidth().background(MaterialTheme.colorScheme.surface).padding(12.dp),
                    color = Color.Gray, style = MaterialTheme.typography.bodySmall)
            }
            if (here.isNotEmpty() && viewer == null && !personView && screen !is Screen.Suggest && area != "all") {   // thanh thao tác dưới (trang người và trang đề xuất đã có nút lệnh ở hàng trên) khi đang chọn ảnh (trang một người dùng các nút tròn nổi)
                Row(Modifier.fillMaxWidth().background(MaterialTheme.colorScheme.surface).horizontalScroll(rememberScrollState()).padding(vertical = 4.dp), horizontalArrangement = Arrangement.SpaceEvenly) {
                    SelAction("add", "Thêm vào tên") { dlg = "add" }
                    if (area != "all") for ((code, name) in CLOTHES) SelAction(code, name) { doClassify(code, name) }          // tab All đã có Dressed / Naked ở các nút tròn phía trên; còn lại: bấm Dressed / Naked: các ảnh đã chọn chuyển ngay sang loại đó
                    (screen as? Screen.PersonView)?.p?.let { pp ->
                        SelAction("remove", "Loại khỏi danh sách") {
                            val ids = here.toList()
                            scope.launch {
                                try { Store.personRemove(pp, ids) } catch (e: Exception) { }
                                Store.selected = Store.selected - ids.toSet()
                                undo = UndoItem("Đã loại khỏi danh sách", ids) { Store.personRestore(pp, ids) }
                            }
                        }
                    }
                }
            }
            if (screen is Screen.Tabs) {
                // thanh điều hướng dưới đáy: Model, All, Mashup, Favorite, Cài đặt
                NavigationBar {
                    for ((key, label) in listOf("model" to "Model", "all" to "All", "combo" to "Mashup", "fav" to "Favorite", "settings" to "Cài đặt")) {
                        NavigationBarItem(
                            selected = area == key,
                            onClick = { area = key; locateUid = null },
                            icon = { NavIcon(key, if (area == key) MaterialTheme.colorScheme.primary else Color.Gray) },
                            label = { Text(label, maxLines = 1) },
                            alwaysShowLabel = true)
                    }
                }
            }
        }
        viewer?.let { (list, i) ->
            ViewerScreen(list, i, fromPerson, fromSuggest,
                onPerson = { p -> viewer = null; screen = Screen.PersonView(p) },                       // bấm tên người: mở trang ảnh của người đó
                onLocate = { im -> viewer = null; screen = Screen.Tabs; area = "all"; locateUid = im.uid }) { viewer = null }
        }
    }
    BackArrowIndicator()
    if (dlg == "add") PersonPickDialog({ pick = it; dlg = "confirmAdd" }, { nm -> newName = nm; dlg = "confirmCreate" }, { dlg = "" })
    val pk = pick
    if (dlg == "confirmAdd" && pk != null) AlertDialog(onDismissRequest = { dlg = "" }, title = { Text("Xác nhận") },
        text = { Text("Thêm ${here.size} ảnh đã chọn ở danh sách này vào ${pk.name.ifEmpty { "Chưa đặt tên" }}?") },
        confirmButton = { TextButton({
            dlg = ""; val ids = here.toList()
            scope.launch {
                try { Store.personAdd(pk, ids) } catch (e: Exception) { }
                (screen as? Screen.Suggest)?.p?.let { sp -> try { Store.guessReject(sp, ids) } catch (e: Exception) { } }
                Store.selected = Store.selected - ids.toSet()
                undo = UndoItem("Đã thêm vào ${pk.name.ifEmpty { "Chưa đặt tên" }}", ids) { Store.personRemove(pk, ids) }
            }
        }) { Text("Thêm") } },
        dismissButton = { TextButton({ dlg = "" }) { Text("Hủy") } })
    if (dlg == "confirmCreate") AlertDialog(onDismissRequest = { dlg = "" }, title = { Text("Xác nhận") },
        text = { Text("Tạo người mới “${newName.trim()}” và thêm ${here.size} ảnh đã chọn ở danh sách này vào?") },
        confirmButton = { TextButton({
            dlg = ""; val ids = here.toList(); val nm = newName
            scope.launch {
                try {
                    val np = Store.personCreate(nm, ids)
                    (screen as? Screen.Suggest)?.p?.let { sp -> try { Store.guessReject(sp, ids) } catch (e: Exception) { } }
                    undo = UndoItem("Đã tạo “${nm.trim()}”", ids) { Store.personRemove(np, ids) }
                } catch (e: Exception) { }
                Store.selected = Store.selected - ids.toSet()
            }
        }) { Text("Tạo") } },
        dismissButton = { TextButton({ dlg = "" }) { Text("Hủy") } })
    if (note.isNotEmpty()) AlertDialog(onDismissRequest = { note = "" }, confirmButton = { TextButton({ note = "" }) { Text("Đóng") } }, title = { Text("Chọn ảnh tương tự") }, text = { Text(note) })
}

class UndoItem(val text: String, val uids: List<String>, val revert: suspend () -> Unit)

/** Biểu tượng vẽ nét dùng chung (thanh thao tác, nút tròn). */
@Composable
fun KindIcon(kind: String, c: Color, dp: androidx.compose.ui.unit.Dp) {
    androidx.compose.foundation.Canvas(Modifier.size(dp)) {
            val w = size.width
            val st = androidx.compose.ui.graphics.drawscope.Stroke(width = w * 0.09f, cap = androidx.compose.ui.graphics.StrokeCap.Round)
            when (kind) {
                "back" -> {                                                        // mũi tên quay lại
                    val a = androidx.compose.ui.graphics.Path().apply { moveTo(w * 0.62f, w * 0.18f); lineTo(w * 0.28f, w * 0.5f); lineTo(w * 0.62f, w * 0.82f) }
                    drawPath(a, c, style = androidx.compose.ui.graphics.drawscope.Stroke(width = w * 0.11f, cap = androidx.compose.ui.graphics.StrokeCap.Round, join = androidx.compose.ui.graphics.StrokeJoin.Round))
                    drawLine(c, Offset(w * 0.3f, w * 0.5f), Offset(w * 0.8f, w * 0.5f), strokeWidth = w * 0.11f, cap = androidx.compose.ui.graphics.StrokeCap.Round)
                }
                "person" -> {                                                      // hình người
                    drawCircle(c, w * 0.17f, Offset(w * 0.5f, w * 0.3f), style = st)
                    drawArc(c, 180f, 180f, false, Offset(w * 0.17f, w * 0.52f), androidx.compose.ui.geometry.Size(w * 0.66f, w * 0.5f), style = st)
                }
                "tick" -> {                                                        // dấu tick
                    val a = androidx.compose.ui.graphics.Path().apply { moveTo(w * 0.22f, w * 0.54f); lineTo(w * 0.42f, w * 0.74f); lineTo(w * 0.8f, w * 0.28f) }
                    drawPath(a, c, style = androidx.compose.ui.graphics.drawscope.Stroke(width = w * 0.12f, cap = androidx.compose.ui.graphics.StrokeCap.Round, join = androidx.compose.ui.graphics.StrokeJoin.Round))
                }
                "enter" -> {                                                       // phím Enter: mũi tên gập (xuống rồi sang trái)
                    val a = androidx.compose.ui.graphics.Path().apply { moveTo(w * 0.8f, w * 0.22f); lineTo(w * 0.8f, w * 0.6f); lineTo(w * 0.24f, w * 0.6f) }
                    drawPath(a, c, style = androidx.compose.ui.graphics.drawscope.Stroke(width = w * 0.1f, cap = androidx.compose.ui.graphics.StrokeCap.Round, join = androidx.compose.ui.graphics.StrokeJoin.Round))
                    val h = androidx.compose.ui.graphics.Path().apply { moveTo(w * 0.42f, w * 0.42f); lineTo(w * 0.24f, w * 0.6f); lineTo(w * 0.42f, w * 0.78f) }
                    drawPath(h, c, style = androidx.compose.ui.graphics.drawscope.Stroke(width = w * 0.1f, cap = androidx.compose.ui.graphics.StrokeCap.Round, join = androidx.compose.ui.graphics.StrokeJoin.Round))
                }
                "close" -> {
                    drawLine(c, Offset(w * 0.25f, w * 0.25f), Offset(w * 0.75f, w * 0.75f), strokeWidth = w * 0.11f, cap = androidx.compose.ui.graphics.StrokeCap.Round)
                    drawLine(c, Offset(w * 0.75f, w * 0.25f), Offset(w * 0.25f, w * 0.75f), strokeWidth = w * 0.11f, cap = androidx.compose.ui.graphics.StrokeCap.Round)
                }
                "plus" -> {
                    drawLine(c, Offset(w * 0.5f, w * 0.22f), Offset(w * 0.5f, w * 0.78f), strokeWidth = w * 0.11f, cap = androidx.compose.ui.graphics.StrokeCap.Round)
                    drawLine(c, Offset(w * 0.22f, w * 0.5f), Offset(w * 0.78f, w * 0.5f), strokeWidth = w * 0.11f, cap = androidx.compose.ui.graphics.StrokeCap.Round)
                }
                "dots" -> {                                                        // ba chấm ngang
                    for (k in 0..2) drawCircle(c, w * 0.07f, Offset(w * (0.22f + 0.28f * k), w * 0.5f))
                }
                "add" -> {                                                         // người + dấu cộng
                    drawCircle(c, w * 0.16f, Offset(w * 0.4f, w * 0.3f), style = st)
                    drawArc(c, 180f, 180f, false, Offset(w * 0.08f, w * 0.52f), androidx.compose.ui.geometry.Size(w * 0.64f, w * 0.5f), style = st)
                    drawLine(c, Offset(w * 0.8f, w * 0.2f), Offset(w * 0.8f, w * 0.5f), strokeWidth = w * 0.09f, cap = androidx.compose.ui.graphics.StrokeCap.Round)
                    drawLine(c, Offset(w * 0.65f, w * 0.35f), Offset(w * 0.95f, w * 0.35f), strokeWidth = w * 0.09f, cap = androidx.compose.ui.graphics.StrokeCap.Round)
                }
                "remove" -> {                                                      // người + dấu trừ (đồng bộ với "add")
                    drawCircle(c, w * 0.16f, Offset(w * 0.4f, w * 0.3f), style = st)
                    drawArc(c, 180f, 180f, false, Offset(w * 0.08f, w * 0.52f), androidx.compose.ui.geometry.Size(w * 0.64f, w * 0.5f), style = st)
                    drawLine(c, Offset(w * 0.65f, w * 0.35f), Offset(w * 0.95f, w * 0.35f), strokeWidth = w * 0.09f, cap = androidx.compose.ui.graphics.StrokeCap.Round)
                }
                "create" -> {                                                      // dấu cộng trong vòng tròn
                    drawCircle(c, w * 0.42f, Offset(w * 0.5f, w * 0.5f), style = st)
                    drawLine(c, Offset(w * 0.5f, w * 0.3f), Offset(w * 0.5f, w * 0.7f), strokeWidth = w * 0.09f, cap = androidx.compose.ui.graphics.StrokeCap.Round)
                    drawLine(c, Offset(w * 0.3f, w * 0.5f), Offset(w * 0.7f, w * 0.5f), strokeWidth = w * 0.09f, cap = androidx.compose.ui.graphics.StrokeCap.Round)
                }
                "cloth" -> {                                                       // Dressed: áo bơi dây cổ (hai mảnh tam giác + dây buộc cổ)
                    val cupL = androidx.compose.ui.graphics.Path().apply {
                        moveTo(w * 0.27f, w * 0.50f); quadraticBezierTo(w * 0.17f, w * 0.66f, w * 0.14f, w * 0.80f)
                        quadraticBezierTo(w * 0.28f, w * 0.89f, w * 0.43f, w * 0.80f)
                        quadraticBezierTo(w * 0.34f, w * 0.62f, w * 0.27f, w * 0.50f); close()
                    }
                    val cupR = androidx.compose.ui.graphics.Path().apply {
                        moveTo(w * 0.73f, w * 0.50f); quadraticBezierTo(w * 0.83f, w * 0.66f, w * 0.86f, w * 0.80f)
                        quadraticBezierTo(w * 0.72f, w * 0.89f, w * 0.57f, w * 0.80f)
                        quadraticBezierTo(w * 0.66f, w * 0.62f, w * 0.73f, w * 0.50f); close()
                    }
                    drawPath(cupL, c); drawPath(cupR, c)
                    val rope = androidx.compose.ui.graphics.drawscope.Stroke(width = w * 0.05f, cap = androidx.compose.ui.graphics.StrokeCap.Round)
                    val strL = androidx.compose.ui.graphics.Path().apply { moveTo(w * 0.5f, w * 0.20f); cubicTo(w * 0.40f, w * 0.28f, w * 0.31f, w * 0.40f, w * 0.27f, w * 0.50f) }
                    val strR = androidx.compose.ui.graphics.Path().apply { moveTo(w * 0.5f, w * 0.20f); cubicTo(w * 0.60f, w * 0.28f, w * 0.69f, w * 0.40f, w * 0.73f, w * 0.50f) }
                    drawPath(strL, c, style = rope); drawPath(strR, c, style = rope)
                    drawLine(c, Offset(w * 0.43f, w * 0.80f), Offset(w * 0.57f, w * 0.80f), strokeWidth = w * 0.04f, cap = androidx.compose.ui.graphics.StrokeCap.Round)
                    drawOval(c, Offset(w * 0.40f, w * 0.095f), androidx.compose.ui.geometry.Size(w * 0.10f, w * 0.07f))     // nút buộc: hai cánh
                    drawOval(c, Offset(w * 0.50f, w * 0.095f), androidx.compose.ui.geometry.Size(w * 0.10f, w * 0.07f))
                }
                "nude" -> {                                                        // Naked: nét vẽ dáng cơ thể (hai đường cong ôm hông, rãnh giữa)
                    val line = androidx.compose.ui.graphics.drawscope.Stroke(width = w * 0.06f, cap = androidx.compose.ui.graphics.StrokeCap.Round)
                    val left = androidx.compose.ui.graphics.Path().apply { moveTo(w * 0.44f, w * 0.15f); cubicTo(w * 0.20f, w * 0.32f, w * 0.13f, w * 0.60f, w * 0.40f, w * 0.93f) }
                    val right = androidx.compose.ui.graphics.Path().apply { moveTo(w * 0.56f, w * 0.15f); cubicTo(w * 0.80f, w * 0.32f, w * 0.87f, w * 0.60f, w * 0.60f, w * 0.93f) }
                    drawPath(left, c, style = line); drawPath(right, c, style = line)
                    val hookL = androidx.compose.ui.graphics.Path().apply { moveTo(w * 0.31f, w * 0.07f); quadraticBezierTo(w * 0.41f, w * 0.13f, w * 0.36f, w * 0.25f) }
                    val hookR = androidx.compose.ui.graphics.Path().apply { moveTo(w * 0.69f, w * 0.07f); quadraticBezierTo(w * 0.59f, w * 0.13f, w * 0.64f, w * 0.25f) }
                    drawPath(hookL, c, style = line); drawPath(hookR, c, style = line)
                    val arcL = androidx.compose.ui.graphics.Path().apply { moveTo(w * 0.22f, w * 0.64f); quadraticBezierTo(w * 0.46f, w * 0.62f, w * 0.50f, w * 0.40f) }
                    val arcR = androidx.compose.ui.graphics.Path().apply { moveTo(w * 0.78f, w * 0.64f); quadraticBezierTo(w * 0.54f, w * 0.62f, w * 0.50f, w * 0.40f) }
                    drawPath(arcL, c, style = line); drawPath(arcR, c, style = line)
                    drawLine(c, Offset(w * 0.5f, w * 0.40f), Offset(w * 0.5f, w * 0.96f), strokeWidth = w * 0.05f, cap = androidx.compose.ui.graphics.StrokeCap.Round)
                }
                else -> {                                                          // dấu trừ trong vòng tròn
                    drawCircle(c, w * 0.42f, Offset(w * 0.5f, w * 0.5f), style = st)
                    drawLine(c, Offset(w * 0.3f, w * 0.5f), Offset(w * 0.7f, w * 0.5f), strokeWidth = w * 0.09f, cap = androidx.compose.ui.graphics.StrokeCap.Round)
                }
            }
        }
}

/** Nút tròn nổi trên ảnh (nền đen mờ, ảnh phía dưới vẫn thấy xung quanh). */
@Composable
fun RoundBtn(active: Boolean = false, onClick: () -> Unit, content: @Composable () -> Unit) {
    // phản hồi để biết nút có hiệu lực: nút trạng thái (active) tô sáng liên tục; nút lệnh sáng lên khi đang chạm và nháy sáng một lần khi bấm xong
    val src = remember { androidx.compose.foundation.interaction.MutableInteractionSource() }
    val pressed by src.collectIsPressedAsState()
    var flash by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val bg by androidx.compose.animation.animateColorAsState(if (active || pressed || flash) Brass else BtnFill, tween(110), label = "btn")
    Box(Modifier.size(LocalBtn.current).clip(CircleShape).background(bg).border(1.5.dp, BtnLine, CircleShape)
        .clickable(interactionSource = src, indication = null) { onClick(); scope.launch { flash = true; delay(280); flash = false } }, contentAlignment = Alignment.Center) { content() }
}

/** Đường kính D của các nút tròn hàng trên (bề ngang màn hình / 8,5); nền nút (BtnFill) trong suốt, chỉ có viền mảnh. */
val LocalBtn = androidx.compose.runtime.compositionLocalOf { 46.dp }
val BtnFill = Color(0x8C000000)          // đen nhạt (khoảng 55%), vẫn hơi trong
val BtnLine = Color(0xB3FFFFFF)

/** Khoảng đệm phía trên lưới ảnh: hàng ảnh đầu tiên cách các nút tròn 0,25D (D = bề ngang màn hình / 8,5); khi cuộn lên ảnh vẫn trôi lên nằm dưới các nút. */
@Composable
fun topBarSpace(): androidx.compose.ui.unit.Dp {
    val d = androidx.compose.ui.platform.LocalConfiguration.current.screenWidthDp.dp / 8.5f
    return 10.dp + d * 1.25f
}

/** Biểu tượng / chữ trong nút tròn hàng trên: cỡ theo D để luôn nằm chính giữa và cân đối. */
@Composable
fun BtnIcon(kind: String) = KindIcon(kind, Color.White, LocalBtn.current * 0.52f)

@Composable
fun BtnText(t: String, bold: Boolean = false) {
    val sp = with(androidx.compose.ui.platform.LocalDensity.current) { (LocalBtn.current * 0.42f).toSp() }
    Text(t, color = Color.White, fontSize = sp, fontWeight = if (bold) androidx.compose.ui.text.font.FontWeight.Bold else null, lineHeight = sp)
}

/** Vuốt từ cạnh màn hình vào để quay lại: hiện mũi tên quay lại ngay tại chỗ ngón tay vuốt (theo tiến độ vuốt); thả ra thì thực hiện quay lại, kéo ngược về thì hủy. */
@Composable
fun EdgeBack(enabled: Boolean, onBack: () -> Unit) {
    androidx.activity.compose.PredictiveBackHandler(enabled) { events ->
        try {
            events.collect { e -> Store.backP = e.progress; Store.backY = e.touchY; Store.backRight = e.swipeEdge == androidx.activity.BackEventCompat.EDGE_RIGHT }
            Store.backP = 0f
            onBack()
        } catch (c: kotlin.coroutines.cancellation.CancellationException) {
            Store.backP = 0f
            throw c
        }
    }
}

/** Mũi tên quay lại hiện ở cạnh màn hình, đúng độ cao ngón tay vuốt. */
@Composable
fun BackArrowIndicator() {
    val p = Store.backP
    if (p <= 0f) return
    val d = androidx.compose.ui.platform.LocalDensity.current
    Box(Modifier.fillMaxSize()) {
        val sz = 44.dp
        val y = with(d) { Store.backY.toDp() } - sz / 2
        val x = (-sz.value * (1f - p.coerceIn(0f, 1f) * 1.1f)).dp.coerceAtMost(8.dp)             // trượt vào từ mép theo tiến độ vuốt
        Box(Modifier.align(if (Store.backRight) Alignment.TopEnd else Alignment.TopStart).offset(x = if (Store.backRight) -x else x, y = y.coerceAtLeast(0.dp)).size(sz)
            .shadow(6.dp, CircleShape).background(Color(0xE6000000), CircleShape).border(1.dp, Color(0x55FFFFFF), CircleShape), contentAlignment = Alignment.Center) {
            Box(Modifier.graphicsLayer { scaleX = if (Store.backRight) -1f else 1f }) { KindIcon("back", Color.White, 22.dp) }
        }
    }
}

/** Hàng nút phía trên ảnh: nhóm nút bên trái, ô dài ở giữa, nhóm nút bên phải. */
@Composable
fun TopBar(modifier: Modifier, left: @Composable RowScope.() -> Unit, center: @Composable () -> Unit, right: @Composable RowScope.() -> Unit) {
    // bố cục theo đường kính D của nút tròn (D = bề ngang / 8,5): mép → nút ngoài cùng 0,25D; nút ngoài cùng → nút kế → ô dài đều 0,25D; ô dài rộng đúng 3D
    androidx.compose.foundation.layout.BoxWithConstraints(modifier.fillMaxWidth().padding(vertical = 10.dp)) {
        val d = maxWidth / 8.5f
        androidx.compose.runtime.CompositionLocalProvider(LocalBtn provides d) {
            Box(Modifier.fillMaxWidth().height(d)) {
                Row(Modifier.align(Alignment.CenterStart).padding(start = d * 0.25f), horizontalArrangement = Arrangement.spacedBy(d * 0.25f), content = left)
                Box(Modifier.align(Alignment.Center)) { center() }
                Row(Modifier.align(Alignment.CenterEnd).padding(end = d * 0.25f), horizontalArrangement = Arrangement.spacedBy(d * 0.25f), content = right)
            }
        }
    }
}

/** Ô dài gộp 3 nút Dressed | Naked | All ở giữa hàng nút phía trên ảnh (nền đen mờ như các nút tròn, ô đang chọn tô màu vàng đồng). */
@Composable
fun ClothPill(cloth: String?, selecting: Boolean, third: String? = null, thirdOn: Boolean = false, onThird: () -> Unit = {}, showThird: Boolean = true, thirdKind: String? = null, onPick: (String?) -> Unit) {
    val d = LocalBtn.current
    Row(Modifier.width(d * (if (showThird) 3 else 2)).height(d).clip(CircleShape).background(BtnFill).border(1.5.dp, BtnLine, CircleShape)) {          // rộng đúng 3 hình tròn
        val opts = if (showThird) listOf<String?>("cloth", "nude", null) else listOf<String?>("cloth", "nude")
        for (c in opts) {
            val on = if (c == null && (third != null || thirdKind != null)) thirdOn else cloth == c && !selecting
            Box(Modifier.size(d).clip(CircleShape).background(if (on) Brass else Color.Transparent).clickable { if (c == null && (third != null || thirdKind != null)) onThird() else onPick(c) }, contentAlignment = Alignment.Center) {   // ô sáng là hình tròn hoàn hảo
                if (c == null && thirdKind != null) BtnIcon(thirdKind)
                else if (c == null && third != null) BtnText(third)
                else if (c == null) BtnText("All", true) else KindIcon(c, Color.White, d * 0.52f)
            }
        }
    }
}

/** Một nút trên thanh thao tác khi đang chọn ảnh: biểu tượng vẽ nét + chữ nhỏ. */
@Composable
fun SelAction(kind: String, label: String, onClick: () -> Unit) {
    Column(Modifier.clickable { onClick() }.padding(horizontal = 14.dp, vertical = 6.dp), horizontalAlignment = Alignment.CenterHorizontally) {
        val c = MaterialTheme.colorScheme.primary
        KindIcon(kind, MaterialTheme.colorScheme.primary, 26.dp)
        Text(label, style = MaterialTheme.typography.labelSmall, maxLines = 1)
    }
}

/** Chọn một người có sẵn để thêm ảnh vào: gõ để tìm, kèm ảnh đại diện để so sánh. */
@Composable
fun PersonPickDialog(onPick: (Person) -> Unit, onCreate: (String) -> Unit, onDismiss: () -> Unit) {
    var q by remember { mutableStateOf("") }
    val all = remember(Store.persons) { Store.persons.filter { it.n > 0 && it.name.isNotEmpty() }.sortedBy { foldVi(it.name) } }
    val key = foldVi(q.trim())
    val hits = (if (key.isEmpty()) all else all.filter { foldVi(it.name).contains(key) }).take(60)
    AlertDialog(onDismissRequest = onDismiss, title = { Text("Thêm vào tên") },
        text = {
            Column {
                Row(verticalAlignment = Alignment.CenterVertically) {          // ô tìm tên + nút + (tạo tên mới nếu chưa có trong gợi ý)
                    OutlinedTextField(q, { q = it }, label = { Text("Tìm hoặc nhập tên") }, singleLine = true, modifier = Modifier.weight(1f))
                    val can = q.isNotBlank()
                    Box(Modifier.padding(start = 8.dp).size(44.dp).clip(CircleShape).background(if (can) Brass else Color(0x33888888))
                        .clickable(enabled = can) { onCreate(q.trim()) }, contentAlignment = Alignment.Center) {
                        KindIcon("plus", Color.White, 22.dp)
                    }
                }
                if (hits.isEmpty() && q.isNotBlank()) Text("Chưa có tên “${q.trim()}”. Bấm dấu + để tạo tên mới.", Modifier.padding(top = 10.dp), color = Color.Gray, style = MaterialTheme.typography.bodySmall)
                LazyColumn(Modifier.heightIn(max = 320.dp)) {
                    items(hits, key = { it.id }) { p ->
                        Row(Modifier.fillMaxWidth().clickable { onPick(p) }.padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                            CoverPhoto(p.id, Store.covers[p.id], Modifier.padding(end = 12.dp).size(44.dp).clip(CircleShape))
                            Column { Text(p.name); Text("${p.n} ảnh", color = Color.Gray, style = MaterialTheme.typography.bodySmall) }
                        }
                    }
                }
            }
        },
        confirmButton = {}, dismissButton = { TextButton(onDismiss) { Text("Hủy") } })
}

/** Nút ⋮ mở "Chế độ xem ảnh" (bố cục, hiện ngày): có ở mọi màn hình xem ảnh. */
@Composable
fun ViewMenuButton() {
    var d by remember { mutableStateOf(false) }
    TextButton({ d = true }) { Text("⋯") }
    if (d) ViewSettingsDialog { d = false }
}

/** Chế độ xem ảnh: bố cục (Vừa vặn / Ngày / Tháng) và hiện ngày trong lưới (menu ⋮). */
@Composable
fun ViewSettingsDialog(onClose: () -> Unit) {
    AlertDialog(onDismissRequest = onClose, title = { Text("Chế độ xem ảnh") },
        text = {
            Column {
                Text("Bố cục", color = Color.Gray)
                Row(Modifier.padding(vertical = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    for ((k, t) in listOf("fit" to "Vừa vặn", "day" to "Ngày", "month" to "Tháng")) FilterPill(t, Store.layout == k) { Store.setView(k, Store.showDates) }
                }
                Row(Modifier.fillMaxWidth().padding(top = 8.dp), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                    Text("Hiện ngày trong lưới")
                    androidx.compose.material3.Switch(checked = Store.showDates, onCheckedChange = { Store.setView(Store.layout, it) })
                }
            }
        },
        confirmButton = { TextButton(onClose) { Text("Xong") } })
}

/** Biểu tượng vẽ bằng nét cho thanh điều hướng: Model (người), All (khung ảnh), Mashup (hai vòng chồng), Favorite (trái tim). */
@Composable
fun NavIcon(kind: String, color: Color) {
    androidx.compose.foundation.Canvas(Modifier.size(24.dp)) {
        val w = size.width
        val st = androidx.compose.ui.graphics.drawscope.Stroke(width = w * 0.09f, cap = androidx.compose.ui.graphics.StrokeCap.Round, join = androidx.compose.ui.graphics.StrokeJoin.Round)
        when (kind) {
            "model" -> {
                drawCircle(color, w * 0.18f, Offset(w * 0.5f, w * 0.32f), style = st)
                val p = androidx.compose.ui.graphics.Path().apply {
                    moveTo(w * 0.16f, w * 0.88f); cubicTo(w * 0.16f, w * 0.58f, w * 0.84f, w * 0.58f, w * 0.84f, w * 0.88f)
                }
                drawPath(p, color, style = st)
            }
            "all" -> {
                drawRoundRect(color, Offset(w * 0.12f, w * 0.18f), androidx.compose.ui.geometry.Size(w * 0.76f, w * 0.64f), androidx.compose.ui.geometry.CornerRadius(w * 0.1f), style = st)
                drawCircle(color, w * 0.07f, Offset(w * 0.34f, w * 0.38f), style = st)
                val p = androidx.compose.ui.graphics.Path().apply { moveTo(w * 0.14f, w * 0.74f); lineTo(w * 0.42f, w * 0.52f); lineTo(w * 0.6f, w * 0.66f); lineTo(w * 0.72f, w * 0.56f); lineTo(w * 0.86f, w * 0.7f) }
                drawPath(p, color, style = st)
            }
            "combo" -> {
                drawCircle(color, w * 0.26f, Offset(w * 0.36f, w * 0.5f), style = st)
                drawCircle(color, w * 0.26f, Offset(w * 0.64f, w * 0.5f), style = st)
            }
            "settings" -> {
                drawCircle(color, w * 0.14f, Offset(w * 0.5f, w * 0.5f), style = st)
                for (k in 0 until 8) {
                    val a = Math.toRadians(k * 45.0)
                    drawLine(color, Offset(w * 0.5f + (w * 0.26f * Math.cos(a)).toFloat(), w * 0.5f + (w * 0.26f * Math.sin(a)).toFloat()),
                        Offset(w * 0.5f + (w * 0.38f * Math.cos(a)).toFloat(), w * 0.5f + (w * 0.38f * Math.sin(a)).toFloat()), strokeWidth = w * 0.09f, cap = androidx.compose.ui.graphics.StrokeCap.Round)
                }
            }
            else -> {                                                       // Favorite: ngôi sao (ảnh yêu thích); trái tim chỉ dùng cho người ở trang Model
                val p = androidx.compose.ui.graphics.Path()
                for (k in 0 until 10) {
                    val r = if (k % 2 == 0) w * 0.42f else w * 0.18f
                    val ang = Math.toRadians(-90.0 + k * 36.0)
                    val x = w * 0.5f + (r * Math.cos(ang)).toFloat(); val y = w * 0.54f + (r * Math.sin(ang)).toFloat()
                    if (k == 0) p.moveTo(x, y) else p.lineTo(x, y)
                }
                p.close()
                drawPath(p, color, style = st)
            }
        }
    }
}

@Composable
fun Thumb(uid: String, modifier: Modifier = Modifier, alignment: Alignment = Alignment.Center) {
    val b by produceState<Bitmap?>(null, uid) { value = Store.thumb(uid) }
    Box(modifier.background(Color(0xFFE6DFCF))) {
        b?.let { Image(it.asImageBitmap(), null, Modifier.fillMaxSize(), contentScale = ContentScale.Crop, alignment = alignment) }
    }
}

/** Chọn một nhãn có sẵn hoặc gõ tên mới. */
@Composable
fun LabelPicker(title: String, options: List<String>, allowNew: Boolean, onPick: (String) -> Unit, onDismiss: () -> Unit) {
    var text by remember { mutableStateOf("") }
    AlertDialog(onDismissRequest = onDismiss, title = { Text(title) },
        text = {
            Column {
                Column(Modifier.heightIn(max = 280.dp).horizontalScroll(rememberScrollState(), enabled = false)) {
                    LazyColumn(Modifier.heightIn(max = 280.dp)) {
                        items(options) { o -> Text(o, Modifier.fillMaxWidth().clickable { onPick(o) }.padding(vertical = 12.dp)) }
                    }
                }
                if (allowNew) OutlinedTextField(text, { text = it }, label = { Text("Nhãn mới") }, singleLine = true, modifier = Modifier.fillMaxWidth())
            }
        },
        confirmButton = { if (allowNew) TextButton({ if (text.isNotBlank()) onPick(text.trim()) }) { Text("Thêm") } },
        dismissButton = { TextButton(onDismiss) { Text("Hủy") } })
}

/** Ô tick tự vẽ (không phụ thuộc giao diện hệ thống): 0 chưa có, 1 một số ảnh đã có (dấu –), 2 tất cả ảnh đã có (dấu ✓). */
@Composable
fun TickBox(state: Int) {
    val shape = RoundedCornerShape(6.dp)
    Box(Modifier.size(26.dp).background(if (state > 0) Brass else Color.Transparent, shape)
        .border(2.dp, if (state > 0) Brass else Color(0xFF8A8478), shape), contentAlignment = Alignment.Center) {
        if (state == 2) Text("✓", color = Color.White, style = MaterialTheme.typography.titleSmall)
        else if (state == 1) Text("–", color = Color.White, style = MaterialTheme.typography.titleMedium)
    }
}

/** Danh sách nhãn có ô tick cho một hoặc nhiều ảnh: chạm một nhãn để thêm (hoặc bỏ nếu mọi ảnh đã có) cho tất cả ảnh đang chọn. */
@Composable
fun LabelTickList(uids: List<String>) {
    val v = Store.version                                   // đọc ngay trong composable này để ô tick tự cập nhật sau mỗi lần chạm
    val scope = rememberCoroutineScope()
    LazyColumn(Modifier.heightIn(max = 300.dp)) {
        items(Store.labels, key = { it.id }) { l ->
            val n = uids.count { Store.labelOf[it]?.contains(l.id) == true }
            val state = if (n == 0) 0 else if (n == uids.size) 2 else 1
            Row(Modifier.fillMaxWidth().clickable {
                scope.launch { try { if (state == 2) Store.labelRemove(uids, l.name) else Store.labelAdd(uids, l.name) } catch (e: Exception) { } }
            }.padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                TickBox(state)
                Text(l.name + if (uids.size > 1 && n > 0) "   ($n/${uids.size} ảnh)" else "", Modifier.padding(start = 12.dp))
            }
        }
    }
    if (v < 0) Text("")
}

/** Hộp nhãn cho một hoặc nhiều ảnh: mỗi nhãn có ô tick cho biết đã gắn nhãn nào; gõ tên để tạo nhãn mới. */
@Composable
fun LabelTickDialog(uids: List<String>, onClose: () -> Unit) {
    var text by remember { mutableStateOf("") }
    val scope = rememberCoroutineScope()
    AlertDialog(onDismissRequest = onClose, title = { Text(if (uids.size == 1) "Nhãn của ảnh" else "Nhãn cho ${uids.size} ảnh") },
        text = {
            Column {
                Text("Chạm nhãn để gắn hoặc bỏ. ✓ = tất cả ảnh đã có, – = một số ảnh đã có.", Modifier.padding(bottom = 8.dp), color = Color.Gray, style = MaterialTheme.typography.bodySmall)
                LabelTickList(uids)
                OutlinedTextField(text, { text = it }, label = { Text("Nhãn mới") }, singleLine = true, modifier = Modifier.fillMaxWidth().padding(top = 8.dp))
            }
        },
        confirmButton = {
            TextButton({
                if (text.isNotBlank()) { val n = text.trim(); text = ""; scope.launch { try { Store.labelAdd(uids, n) } catch (e: Exception) { } } } else onClose()
            }) { Text(if (text.isBlank()) "Xong" else "Thêm nhãn mới") }
        },
        dismissButton = { TextButton(onClose) { Text("Đóng") } })
}

/** Các thao tác cho nhóm ảnh đang chọn: nhãn (thêm, bỏ, đổi bằng ô tick) và chọn ảnh tương tự. */
@Composable
fun LabelActions(uids: List<String>, done: () -> Unit, select: (Set<String>) -> Unit = {}, pool: List<Img> = emptyList()) {
    var mode by remember { mutableStateOf("") }
    var note by remember { mutableStateOf("") }
    val scope = rememberCoroutineScope()
    Box {
        TextButton({ mode = "cloth" }) { Text("Phân loại") }
        androidx.compose.material3.DropdownMenu(expanded = mode == "cloth", onDismissRequest = { mode = "" }) {
            for ((code, name) in CLOTHES) androidx.compose.material3.DropdownMenuItem(text = { Text(name) }, onClick = {
                mode = ""
                scope.launch { try { Store.setCloth(uids, code) } catch (e: Exception) { }; done() }
            })
        }
    }
    if (pool.isNotEmpty()) TextButton({ mode = "similar" }) { Text("Chọn ảnh tương tự") }
    if (note.isNotEmpty()) AlertDialog(onDismissRequest = { note = "" }, confirmButton = { TextButton({ note = "" }) { Text("Đóng") } }, title = { Text("Chọn ảnh tương tự") }, text = { Text(note) })
    when (mode) {
        "labels" -> LabelTickDialog(uids) { mode = ""; done() }
        "similar" -> LabelPicker("Mức giống", listOf("Rất giống (90%)", "Giống (85%)", "Khá giống (80%)"), false, { lv ->
            mode = ""
            val thr = if (lv.startsWith("Rất")) 0.90f else if (lv.startsWith("Giống")) 0.85f else 0.80f
            scope.launch {
                if (!Store.ensureClip()) note = "Chưa có dữ liệu nhận diện nội dung ảnh. Trên máy tính bấm Đồng bộ ngay, chờ Drive tải lên, rồi bấm ↻ tải lại."
                else {
                    val ids = Store.similar(uids, pool, thr).toSet() + uids
                    select(ids)
                    note = "Đã chọn ${ids.size} ảnh (thêm ${ids.size - uids.size} ảnh giống). Bấm Phân loại để phân loại cho tất cả."
                }
            }
        }, { mode = "" })
    }
}

/** Ngôi sao "béo" đầy đặn (cánh ngắn và tròn), căn theo khung bao nên nằm chính giữa ô chứa nó. */
@Composable
fun FatStar(modifier: Modifier, color: Color) {
    androidx.compose.foundation.Canvas(modifier) {
        val w = size.width
        val r = w * 0.5f
        val inner = r * 0.56f                                              // cánh bên trong lớn hơn sao thường (0,38) nên ngôi sao đầy đặn
        val cx = w / 2f
        val cy = w / 2f + r * 0.0955f                                      // dời xuống để khung bao của ngôi sao (đỉnh trên → hai chân dưới) nằm đúng giữa
        val path = androidx.compose.ui.graphics.Path()
        for (k in 0 until 10) {
            val rr = if (k % 2 == 0) r else inner
            val ang = Math.toRadians(-90.0 + k * 36.0)
            val x = cx + (rr * Math.cos(ang)).toFloat(); val y = cy + (rr * Math.sin(ang)).toFloat()
            if (k == 0) path.moveTo(x, y) else path.lineTo(x, y)
        }
        path.close()
        drawPath(path, color)
        drawPath(path, color, style = androidx.compose.ui.graphics.drawscope.Stroke(width = w * 0.12f, join = androidx.compose.ui.graphics.StrokeJoin.Round))      // viền cùng màu bo tròn góc cho mập hơn
    }
}

/** Có hiện ngôi sao Yêu thích ở góc ảnh không (tắt ở tab Favorite vì ở đó mọi ảnh đều đã là ảnh yêu thích). */
val LocalShowStars = androidx.compose.runtime.compositionLocalOf { true }

/** Một ô ảnh: chạm để xem (hoặc chọn khi đang chọn), bấm giữ hoặc chạm vòng tròn góc trên trái để chọn. */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun Tile(im: Img, on: Boolean, anySel: Boolean, onToggle: () -> Unit, onOpen: () -> Unit, aspect: Float = 1f, fixedH: Float = 0f) {
    // như Google Ảnh: ảnh được chọn thu nhỏ lại và bo tròn góc; ô tròn tick nhỏ ở góc trên trái ảnh, chỉ hiện khi đang ở chế độ chọn
    val sc by androidx.compose.animation.core.animateFloatAsState(if (on) 0.82f else 1f, tween(140), label = "sel")
    val corner by androidx.compose.animation.core.animateDpAsState(if (on) 14.dp else 0.dp, tween(140), label = "corner")
    BoxWithConstraints((if (fixedH > 0f) Modifier.height(fixedH.dp) else Modifier.aspectRatio(aspect)).background(if (on) Color(0x1F888888) else Color.Transparent).clickable { if (anySel) onToggle() else onOpen() }) {
        Thumb(im.uid, Modifier.fillMaxSize().graphicsLayer { scaleX = sc; scaleY = sc }.clip(RoundedCornerShape(corner)))
        val ver = Store.version
        if (LocalShowStars.current && ver >= 0 && Store.isFav(im.uid)) {          // ảnh đã gắn sao Yêu thích: ngôi sao sáng ở góc trên bên trái (khi đang chọn ảnh thì nằm cạnh ô tick)
            Box(Modifier.align(Alignment.TopStart).padding(5.dp).size(18.dp).clip(CircleShape).background(Color(0x66000000)), contentAlignment = Alignment.Center) {        // luôn ở đúng góc này (ô tick che lên khi đang chọn); ngôi sao vẽ nét, nằm chính giữa hình tròn
                FatStar(Modifier.size(11.dp), Color(0xFFFFD05A))
            }
        }
        if (anySel) {
            val dx = maxWidth * (1f - sc) / 2 + 4.dp                           // góc trên trái của ảnh sau khi thu nhỏ
            val dy = maxHeight * (1f - sc) / 2 + 4.dp
            Box(Modifier.offset(x = dx - 6.dp, y = dy - 6.dp).size(32.dp).clickable { onToggle() }, contentAlignment = Alignment.Center) {
                Box(Modifier.size(20.dp)
                    .background(if (on) Brass else Color(0x66000000), CircleShape)
                    .border(1.5.dp, Color.White, CircleShape),
                    contentAlignment = Alignment.Center) {
                    if (on) Text("✓", color = Color.White, fontSize = 12.sp, lineHeight = 12.sp)
                }
            }
        }
    }
}

/** Tốc độ tự cuộn (điểm ảnh mỗi 16 ms) khi ngón tay kéo vào 30% mép dưới / trên khung: càng kéo sâu càng nhanh, đưa ngón tay về giữa khung thì dừng hẳn. */
private fun autoScrollSpeed(y: Float, h: Float): Float {
    val zone = h * 0.3f
    return when {
        y > h - zone -> { val d = ((y - (h - zone)) / zone).coerceIn(0f, 1.6f); 3f + d * d * 22f }
        y < zone -> { val d = ((zone - y) / zone).coerceIn(0f, 1.6f); -(3f + d * d * 22f) }
        else -> 0f
    }
}

/** Chọn theo VÙNG như Google Photos: nhấn giữ một ảnh (mốc), kéo ngón tay tới ảnh khác thì chọn mọi ảnh từ mốc tới đó (kéo ngược lại thì thu nhỏ vùng).
 *  Kéo vào mép dưới / trên khung thì danh sách tự trôi theo, nhanh dần khi kéo sâu và dừng khi đưa tay về giữa khung. */
@Composable
fun Modifier.dragSelect(state: androidx.compose.foundation.lazy.grid.LazyGridState, indexOfUid: (String) -> Int, uidAt: (Int) -> String?): Modifier {
    val scope = rememberCoroutineScope()
    val latest = androidx.compose.runtime.rememberUpdatedState(uidAt)          // luôn dùng danh sách mới nhất (tránh dùng bản cũ sau khi dữ liệu đổi)
    val latestIdx = androidx.compose.runtime.rememberUpdatedState(indexOfUid)
    val pointer = remember { object { var pos = Offset.Zero } }
    return this.pointerInput(state) {
        var anchor: String? = null                                             // ảnh mốc và ảnh dưới ngón tay được nhận theo MÃ ảnh của ô đang hiện trên màn hình (không theo số thứ tự), nên luôn đúng ảnh đang chạm kể cả khi danh sách vừa dồn lên
        var cur: String? = null
        var base = emptySet<String>()
        var job: kotlinx.coroutines.Job? = null
        fun keyAt(off: Offset): String? {
            val info = state.layoutInfo
            val items = info.visibleItemsInfo
            if (items.isEmpty()) return null
            val pad = info.beforeContentPadding.toFloat()                          // vị trí ô được tính từ sau phần đệm phía trên (nút nổi), còn ngón tay tính từ mép trên của lưới: cộng đệm vào để trùng nhau
            items.firstOrNull { off.x >= it.offset.x && off.x < it.offset.x + it.size.width && off.y >= it.offset.y + pad && off.y < it.offset.y + pad + it.size.height }?.let { return it.key as? String }
            val last = items.last()
            val first = items.first()
            return when {
                off.y >= last.offset.y + pad + last.size.height -> last.key as? String      // kéo xuống dưới ảnh cuối đang thấy: tới ảnh cuối
                off.y < first.offset.y + pad -> first.key as? String
                else -> null                                                          // khe giữa các ảnh: giữ nguyên
            }
        }
        fun applyRange(newCur: String) {
            val a = anchor ?: return
            val ia = latestIdx.value(a)
            val ib = latestIdx.value(newCur)
            if (ia < 0 || ib < 0) return                                              // ô tiêu đề ngày / nhóm: không phải ảnh
            cur = newCur
            var s = base
            for (i in minOf(ia, ib)..maxOf(ia, ib)) latest.value(i)?.let { s = s + it }
            Store.selected = s
        }
        // Nhận cử chỉ ở lượt "Initial" (trước các ảnh con): ảnh con có thể đã xử lý chạm của nó nhưng việc nhấn giữ + kéo vẫn hoạt động ở mọi trang xem ảnh.
        awaitEachGesture {
            val down = awaitFirstDown(requireUnconsumed = false, pass = PointerEventPass.Initial)
            val slop = viewConfiguration.touchSlop
            val early = withTimeoutOrNull(viewConfiguration.longPressTimeoutMillis) {
                while (true) {
                    val ev = awaitPointerEvent(PointerEventPass.Initial)
                    val ch = ev.changes.firstOrNull { it.id == down.id } ?: return@withTimeoutOrNull false
                    if (!ch.pressed || (ch.position - down.position).getDistance() > slop) return@withTimeoutOrNull false
                }
                @Suppress("UNREACHABLE_CODE") true
            }
            if (early != null) return@awaitEachGesture                        // thả tay hoặc kéo trước khi đủ lâu: bấm, cuộn như bình thường
            base = Store.selected                                              // đủ lâu: bắt đầu chọn theo vùng từ ảnh này (ảnh mốc)
            anchor = keyAt(down.position)
            cur = null
            pointer.pos = down.position
            anchor?.let { applyRange(it) }
            job?.cancel()
            job = scope.launch {
                while (true) {
                    kotlinx.coroutines.delay(16)
                    val dy = autoScrollSpeed(pointer.pos.y, state.layoutInfo.viewportSize.height.toFloat())
                    if (dy != 0f) {
                        state.dispatchRawDelta(dy)
                        if (anchor != null) keyAt(pointer.pos)?.let { if (it != cur) applyRange(it) }    // nội dung trôi dưới ngón tay: cập nhật vùng chọn
                    }
                }
            }
            try {
                while (true) {
                    val ev = awaitPointerEvent(PointerEventPass.Initial)
                    val ch = ev.changes.firstOrNull { it.id == down.id } ?: break
                    ch.consume()
                    if (!ch.pressed) break
                    pointer.pos = ch.position
                    if (anchor != null) keyAt(ch.position)?.let { if (it != cur) applyRange(it) }
                }
            } finally {
                job?.cancel()
                anchor = null
            }
        }
    }
}

private val WEEKDAYS = arrayOf("CN", "T2", "T3", "T4", "T5", "T6", "T7")

/** "CN, 18 Th5, 2025" từ chuỗi ngày "2025-05-18 ..."; "Không rõ ngày" nếu thiếu. */
fun dayLabel(taken: String): String {
    val m = Regex("^(\\d{4})-(\\d{2})-(\\d{2})").find(taken) ?: return "Không rõ ngày"
    val (y, mo, d) = m.destructured
    val c = java.util.Calendar.getInstance().apply { set(y.toInt(), mo.toInt() - 1, d.toInt()) }
    return "${WEEKDAYS[c.get(java.util.Calendar.DAY_OF_WEEK) - 1]}, ${d.toInt()} Th${mo.toInt()}, $y"
}

fun monthYear(taken: String): String {
    val m = Regex("^(\\d{4})-(\\d{2})").find(taken) ?: return "Không rõ ngày"
    return "Th${m.groupValues[2].toInt()} ${m.groupValues[1]}"
}

private sealed class Entry {
    class Header(val key: String, val text: String) : Entry()
    class Photo(val img: Img, val pos: Int, val span: Int = 1, val h: Float = 0f) : Entry()    // span / h: chỉ dùng ở bố cục Vừa vặn (hàng ảnh đầy bề ngang, cùng chiều cao)
}

/** Thu phóng mượt bằng hai ngón (như Google Ảnh): lưới phóng to / thu nhỏ THEO NGÓN TAY ngay khi đang chụm / giãn (neo tại điểm giữa hai ngón); vượt ngưỡng thì chuyển sang mức kế tiếp
 *  (đổi số ô mỗi hàng) và phần phóng còn dư được trả về 1 từ từ, nên không bị giật. onStep(+1 = giãn / to hơn, -1 = chụm / nhỏ hơn) trả về hệ số kích thước ô mới / cũ, hoặc null nếu hết mức. */
class PinchZoom(val scope: kotlinx.coroutines.CoroutineScope, val onStep: (Int) -> Float?) {
    var live by mutableStateOf(1f)                      // hệ số phóng đang hiển thị
    var origin by mutableStateOf(Offset.Zero)           // điểm giữa hai ngón (px, theo khung lưới): điểm neo của phép phóng
    var size by mutableStateOf(androidx.compose.ui.unit.IntSize.Zero)
    var settling: kotlinx.coroutines.Job? = null
}

@Composable
fun rememberPinchZoom(onStep: (Int) -> Float?): PinchZoom {
    val scope = rememberCoroutineScope()
    val cb by androidx.compose.runtime.rememberUpdatedState(onStep)
    return remember { PinchZoom(scope) { cb(it) } }
}

fun Modifier.pinchZoom(pz: PinchZoom): Modifier = this
    .onSizeChanged { pz.size = it }
    .pointerInput(Unit) {
        awaitEachGesture {
            awaitFirstDown(requireUnconsumed = false, pass = PointerEventPass.Initial)
            var prev = 0f
            var active = false
            while (true) {
                val ev = awaitPointerEvent(PointerEventPass.Initial)
                val pts = ev.changes.filter { it.pressed }
                if (pts.isEmpty()) break
                if (pts.size >= 2) {
                    val d = (pts[0].position - pts[1].position).getDistance()
                    if (!active) { pz.settling?.cancel(); active = true; prev = d }
                    else if (prev > 0f && d > 0f) {
                        pz.origin = (pts[0].position + pts[1].position) / 2f
                        pz.live = (pz.live * (d / prev)).coerceIn(0.55f, 2.2f)
                        prev = d
                        if (pz.live > 1.3f) { val f = pz.onStep(1); if (f != null) pz.live /= f else pz.live = pz.live.coerceAtMost(1.15f) }
                        else if (pz.live < 0.78f) { val f = pz.onStep(-1); if (f != null) pz.live /= f else pz.live = pz.live.coerceAtLeast(0.88f) }
                    }
                    ev.changes.forEach { it.consume() }
                } else if (active) { active = false; prev = 0f }
            }
            if (pz.live != 1f) {                                   // thả tay: phần phóng dư trả về 1 từ từ
                pz.settling = pz.scope.launch { androidx.compose.animation.core.animate(pz.live, 1f, animationSpec = tween(220)) { v, _ -> pz.live = v } }
            }
        }
    }
    .graphicsLayer {
        scaleX = pz.live; scaleY = pz.live
        transformOrigin = androidx.compose.ui.graphics.TransformOrigin(
            if (pz.size.width > 0) pz.origin.x / pz.size.width else 0.5f, if (pz.size.height > 0) pz.origin.y / pz.size.height else 0.5f)
    }

/** Mật độ lưới ảnh: Vừa vặn ↔ Ngày ↔ Tháng. Trả về hệ số kích thước ô (mới / cũ) hoặc null nếu hết mức. */
private fun stepLayout(step: Int): Float? {
    val order = listOf("fit", "day", "month")
    val i = order.indexOf(Store.layout).let { if (it < 0) 1 else it }
    val n = i - step                                               // giãn (+1) về phía Vừa vặn (ảnh to), chụm (-1) về phía Tháng (ảnh nhỏ)
    if (n < 0 || n > order.size - 1) return null
    val cells = mapOf("fit" to 2.2f, "day" to 3f, "month" to 5f)  // số ô mỗi hàng gần đúng
    val f = cells.getValue(order[i]) / cells.getValue(order[n])
    Store.setView(order[n], Store.showDates)
    return f
}

/** Sau khi đổi mật độ lưới bằng thu phóng: ảnh đang nằm dưới điểm giữa hai ngón vẫn nằm đúng chỗ đó trên màn hình (không bị trôi). */
@Composable
private fun LayoutAnchor(state: androidx.compose.foundation.lazy.grid.LazyGridState, entries: List<Entry>, pz: PinchZoom) {
    var last by remember { mutableStateOf(Store.layout) }
    val anchor = remember { arrayOfNulls<Pair<String, Int>>(1) }
    if (last != Store.layout) {
        val info = state.layoutInfo
        val pad = info.beforeContentPadding
        val c = pz.origin
        val items = info.visibleItemsInfo.filter { it.key is String && (it.key as String).length > 2 && !(it.key as String).startsWith("h:") && !(it.key as String).startsWith("g:") }
        val hit = items.firstOrNull { c.x >= it.offset.x && c.x < it.offset.x + it.size.width && c.y >= it.offset.y + pad && c.y < it.offset.y + pad + it.size.height } ?: items.firstOrNull()
        anchor[0] = hit?.let { (it.key as String) to it.offset.y }
        last = Store.layout
    }
    LaunchedEffect(Store.layout) {
        val a = anchor[0] ?: return@LaunchedEffect
        anchor[0] = null
        val idx = entries.indexOfFirst { it is Entry.Photo && it.img.uid == a.first }
        if (idx < 0) return@LaunchedEffect
        state.scrollToItem(idx)
        androidx.compose.runtime.withFrameNanos { }
        val y = state.layoutInfo.visibleItemsInfo.firstOrNull { it.index == idx }?.offset?.y ?: return@LaunchedEffect
        if (y != a.second) state.dispatchRawDelta((y - a.second).toFloat())
    }
}

/** Giữ nguyên vị trí đang xem khi danh sách đổi (ví dụ vừa chuyển các ảnh đã chọn sang loại khác nên chúng biến khỏi danh sách): lấy ảnh còn lại ở trên cùng màn hình làm mốc
 *  và cuộn lại sao cho mốc đó vẫn nằm đúng chỗ cũ trên màn hình, không bị nhảy lên / xuống. */
@Composable
private fun KeepAnchor(state: androidx.compose.foundation.lazy.grid.LazyGridState, entries: List<Entry>) {
    class Pending(val uid: String, val y: Int)
    val last = remember { arrayOf<List<Entry>>(entries) }
    val pending = remember { arrayOfNulls<Pending>(1) }
    if (last[0] !== entries) {
        // đang ở giữa lần dựng lại: layoutInfo vẫn là của danh sách cũ
        val old = last[0]
        last[0] = entries
        pending[0] = null
        fun uids(l: List<Entry>) = l.mapNotNull { (it as? Entry.Photo)?.img?.uid }
        val before = uids(old)
        val after = uids(entries)
        if (before != after) {                                      // chỉ khi tập ảnh thật sự đổi (có ảnh chuyển đi / thêm vào); đổi lựa chọn hay dựng lại danh sách giống hệt thì không động tới vị trí cuộn
            val now = after.toHashSet()
            for (it in state.layoutInfo.visibleItemsInfo) {
                val e = old.getOrNull(it.index) as? Entry.Photo ?: continue
                if (e.img.uid in now) { pending[0] = Pending(e.img.uid, it.offset.y); break }
            }
        }
    }
    LaunchedEffect(entries) {
        val a = pending[0] ?: return@LaunchedEffect
        pending[0] = null
        val idx = entries.indexOfFirst { it is Entry.Photo && it.img.uid == a.uid }
        if (idx < 0) return@LaunchedEffect
        state.scrollToItem(idx)
        androidx.compose.runtime.withFrameNanos { }
        val y = state.layoutInfo.visibleItemsInfo.firstOrNull { it.index == idx }?.offset?.y ?: return@LaunchedEffect
        if (y != a.y) state.dispatchRawDelta((y - a.y).toFloat())
    }
}

/** Bố cục "Vừa vặn" liền mạch như Google Ảnh: xếp ảnh thành từng hàng đầy bề ngang, mỗi hàng cùng chiều cao, độ rộng mỗi ảnh theo tỉ lệ ảnh.
 *  Lưới chia 120 phần; trả về (số phần, chiều cao dp) cho từng ảnh theo thứ tự. */
private fun justifyRows(imgs: List<Img>, widthDp: Float, target: Float = 130f): List<Pair<Int, Float>> {
    val gap = 2f
    val out = ArrayList<Pair<Int, Float>>(imgs.size)
    fun ar(im: Img) = if (im.w > 0 && im.h > 0) (im.w.toFloat() / im.h).coerceIn(0.5f, 2.2f) else 1f
    fun close(row: List<Img>, fill: Boolean) {
        val n = row.size
        val sum = row.sumOf { ar(it).toDouble() }.toFloat()
        val avail = widthDp - gap * (n - 1)
        val h = if (fill) avail / sum else target
        val total = if (fill) 120 else ((sum * target + gap * (n - 1)) / widthDp * 120f).toInt().coerceIn(n, 120)
        val spans = row.map { (total * ar(it) / sum).toInt().coerceAtLeast(1) }.toMutableList()
        var diff = total - spans.sum()
        var k = 0
        while (diff != 0 && k < 1000) { val i = k % n; if (diff > 0) { spans[i]++; diff-- } else if (spans[i] > 1) { spans[i]--; diff++ }; k++ }
        for (i in 0 until n) out.add(spans[i] to h)
    }
    var row = ArrayList<Img>()
    var sum = 0f
    for (im in imgs) {
        row.add(im); sum += ar(im)
        if (sum * target >= widthDp - gap * (row.size - 1)) { close(row, true); row = ArrayList(); sum = 0f }
    }
    if (row.isNotEmpty()) close(row, sum * target >= 0.6f * widthDp)                 // hàng cuối: gần đầy thì kéo cho đầy, còn ít thì giữ cỡ tự nhiên
    return out
}

/** Dòng thời gian như Google Ảnh: mới nhất ở trên, tiêu đề theo ngày, nhãn ngày nổi khi cuộn, thanh kéo nhanh bên phải có mốc năm. */
@Composable
fun TimelineGrid(list: List<Img>, open: (List<Img>, Int) -> Unit, focus: String? = null, topPad: androidx.compose.ui.unit.Dp = 0.dp, actions: @Composable RowScope.(List<String>, () -> Unit, (Set<String>) -> Unit) -> Unit) {
    val sel = Store.selected
    LaunchedEffect(list) { Store.pool = list }                       // "Chọn ảnh tương tự" tìm trong danh sách đang xem
    val state = rememberLazyGridState()
    val scope = rememberCoroutineScope()
    val density = LocalDensity.current
    val fit = Store.layout == "fit"
    val cols = if (fit) 120 else if (Store.layout == "month") 5 else 3
    val wdp = androidx.compose.ui.platform.LocalConfiguration.current.screenWidthDp.toFloat()
    val sig = list.fold(list.size) { h, im -> h * 31 + im.uid.hashCode() }      // chữ ký nội dung danh sách: chỉ dựng lại lưới khi ảnh trong danh sách thật sự đổi
    val entries = remember(sig, Store.showDates, fit, wdp) {
        val out = ArrayList<Entry>(list.size + 64)
        var last = "#"
        val buf = ArrayList<Pair<Img, Int>>()
        fun flush() {
            if (buf.isEmpty()) return
            if (fit) { val jr = justifyRows(buf.map { it.first }, wdp); buf.forEachIndexed { k, (im, i) -> out.add(Entry.Photo(im, i, jr[k].first, jr[k].second)) } }
            else buf.forEach { (im, i) -> out.add(Entry.Photo(im, i)) }
            buf.clear()
        }
        list.forEachIndexed { i, im ->
            val day = if (im.taken.length >= 10) im.taken.substring(0, 10) else ""
            if (day != last) { if (Store.showDates) { flush(); out.add(Entry.Header("h:$day", dayLabel(im.taken))) }; last = day }
            buf.add(im to i)
        }
        flush()
        out
    }
    LaunchedEffect(focus, entries) {                                // "Vị trí": cuộn tới ảnh cần xem và đánh dấu để dễ thấy
        if (focus != null) {
            val idx = entries.indexOfFirst { it is Entry.Photo && it.img.uid == focus }
            if (idx >= 0) state.scrollToItem((idx - 4).coerceAtLeast(0))               // "Tới vị trí": chỉ cuộn tới ảnh
        }
    }
    LaunchedEffect(Store.focusTick) {                               // vừa xem ảnh xong: cuộn tới ảnh đó
        val u = Store.focusUid
        if (u != null) {
            val idx = entries.indexOfFirst { it is Entry.Photo && it.img.uid == u }
            if (idx >= 0) { state.scrollToItem((idx - 3).coerceAtLeast(0)); Store.focusUid = null }
        }
    }
    fun takenAt(index: Int): String {
        var i = index.coerceIn(0, (entries.size - 1).coerceAtLeast(0))
        while (i < entries.size) {
            val e = entries[i]
            if (e is Entry.Photo) return e.img.taken
            i++
        }
        return (entries.lastOrNull { it is Entry.Photo } as? Entry.Photo)?.img?.taken ?: ""
    }
    KeepAnchor(state, entries)
    val pz = rememberPinchZoom { stepLayout(it) }
    LayoutAnchor(state, entries, pz)
    val uidIndex = remember(entries) { HashMap<String, Int>().also { m -> entries.forEachIndexed { i, e -> if (e is Entry.Photo) m[e.img.uid] = i } } }
    val scrolling = state.isScrollInProgress
    var dragging by remember { mutableStateOf(false) }
    var dragFrac by remember { mutableStateOf(0f) }                // vị trí tay nắm theo ngón tay (0–1) khi đang kéo: tay nắm bám sát ngón tay, không đợi danh sách cuộn theo
    var show by remember { mutableStateOf(false) }
    LaunchedEffect(scrolling, dragging) {
        if (scrolling || dragging) show = true else { delay(1600); show = false }
    }
    val total = entries.size.coerceAtLeast(2)
    LaunchedEffect(dragging) {                                       // kéo thanh: danh sách nhảy theo ngón tay, bỏ qua các bước trung gian đã cũ để không bị giật
        if (dragging) snapshotFlow { dragFrac }.collectLatest { f -> state.scrollToItem((f * (total - 1)).toInt().coerceIn(0, total - 1)) }
    }
    Box(Modifier.fillMaxSize()) {
        Column(Modifier.fillMaxSize()) {
          androidx.compose.runtime.key(sig, fit, wdp) {                 // ảnh trong danh sách đổi (vừa chuyển loại): dựng lại các ô từ đầu để không bao giờ còn ô cũ nằm lại; vị trí cuộn giữ nguyên
            LazyVerticalGrid(GridCells.Fixed(cols), Modifier.fillMaxSize().pinchZoom(pz).dragSelect(state, { u -> uidIndex[u] ?: -1 }) { i -> (entries.getOrNull(i) as? Entry.Photo)?.img?.uid }, state = state, contentPadding = PaddingValues(top = topPad), horizontalArrangement = Arrangement.spacedBy(2.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                items(entries.size, key = { i -> when (val e = entries[i]) { is Entry.Header -> e.key; is Entry.Photo -> e.img.uid } },
                    span = { i -> val e = entries[i]; if (e is Entry.Header) GridItemSpan(maxLineSpan) else GridItemSpan((e as Entry.Photo).span) }) { i ->
                    when (val e = entries[i]) {
                        is Entry.Header -> Text(e.text, Modifier.fillMaxWidth().padding(start = 12.dp, top = 14.dp, bottom = 6.dp), style = MaterialTheme.typography.titleSmall)
                        is Entry.Photo -> {
                            val on = e.img.uid in sel
                            Tile(e.img, on, sel.isNotEmpty(), { Store.selected = if (on) sel - e.img.uid else sel + e.img.uid }, { open(list, e.pos) }, 1f, e.h)
                        }
                    }
                }
            }
          }
        }
        // nhãn ngày nổi ở giữa phía trên khi đang cuộn
        if (show && !dragging && entries.isNotEmpty()) {
            Text(dayLabel(takenAt(state.firstVisibleItemIndex)), Modifier.align(Alignment.TopCenter).padding(top = 10.dp)
                .shadow(4.dp, RoundedCornerShape(24.dp)).background(Color.White, RoundedCornerShape(24.dp)).padding(horizontal = 18.dp, vertical = 10.dp),
                color = Color(0xFF1B1812))
        }
        // thanh kéo nhanh bên phải: mốc năm, tay nắm và bong bóng tháng/năm
        if (show && entries.size > 1) {
            BoxWithConstraints(Modifier.align(Alignment.CenterEnd).fillMaxHeight().width(96.dp).padding(vertical = 8.dp)) {
                val h = maxHeight
                val handle = 44.dp
                val frac = if (dragging) dragFrac else {                      // tiến độ liên tục (cộng cả phần đã cuộn trong hàng đầu tiên) nên tay nắm trượt mượt theo từng điểm ảnh
                    val fi = state.layoutInfo.visibleItemsInfo.firstOrNull()
                    val part = if (fi != null && fi.size.height > 0) (state.firstVisibleItemScrollOffset.toFloat() / fi.size.height).coerceIn(0f, 1f) else 0f
                    ((state.firstVisibleItemIndex + part) / (total - 1)).coerceIn(0f, 1f)
                }
                val years = remember(entries) {
                    val seen = LinkedHashMap<String, Int>()
                    entries.forEachIndexed { i, e -> if (e is Entry.Photo && e.img.taken.length >= 4) seen.putIfAbsent(e.img.taken.substring(0, 4), i) }
                    seen.entries.toList()
                }
                val handleY = (h - handle) * frac
                var lastY = -1000f
                for (ent in years) {
                    val yy = (h - handle) * (ent.value.toFloat() / (total - 1)) + handle / 2 - 12.dp
                    val ypx = with(density) { yy.toPx() }
                    if (ypx - lastY < with(density) { 28.dp.toPx() }) continue
                    lastY = ypx
                    Text(ent.key, Modifier.align(Alignment.TopEnd).offset(x = (-8).dp, y = yy)
                        .background(Color(0xE6FFFFFF), RoundedCornerShape(12.dp)).padding(horizontal = 10.dp, vertical = 3.dp), color = Color(0xFF1B1812), style = MaterialTheme.typography.labelLarge)
                }
                if (dragging) {
                    Text(monthYear(takenAt(state.firstVisibleItemIndex)), Modifier.align(Alignment.TopEnd).offset(x = (-56).dp, y = handleY + 4.dp)
                        .shadow(6.dp, RoundedCornerShape(20.dp)).background(Color.White, RoundedCornerShape(20.dp)).padding(horizontal = 16.dp, vertical = 8.dp),
                        color = Color(0xFF1B1812), style = MaterialTheme.typography.titleSmall)
                }
                // chỉ riêng tay nắm nhận cảm ứng (vùng chạm rộng hơn một chút); phần còn lại của mép phải vẫn để chọn / cuộn ảnh bình thường
                val trackPx = with(density) { (h - handle).toPx() }.coerceAtLeast(1f)
                Box(Modifier.align(Alignment.TopEnd).offset(x = 4.dp, y = handleY).size(handle)
                    .shadow(4.dp, CircleShape).background(Color.White, CircleShape)
                    .pointerInput(entries.size, trackPx) {
                        detectVerticalDragGestures(onDragStart = { dragFrac = frac; dragging = true }, onDragEnd = { dragging = false }, onDragCancel = { dragging = false }) { change, dy ->
                            dragFrac = (dragFrac + dy / trackPx).coerceIn(0f, 1f)
                            change.consume()
                        }
                    }, contentAlignment = Alignment.Center) { Text("⇅", color = Color(0xFF1B1812)) }
            }
        }
    }
}

/** Lưới ảnh: bấm giữ để chọn nhiều ảnh (như Google Ảnh), bấm thường để xem; thanh thao tác hiện khi đang chọn. */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun SelGrid(list: List<Img>, open: (List<Img>, Int) -> Unit, actions: @Composable RowScope.(List<String>, () -> Unit, (Set<String>) -> Unit) -> Unit) {
    val sel = Store.selected
    LaunchedEffect(list) { Store.pool = list }
    val sstate = rememberLazyGridState()
    val uidIndex = remember(list) { HashMap<String, Int>().also { m -> list.forEachIndexed { i, im -> m[im.uid] = i } } }
    Column(Modifier.fillMaxSize()) {
        LazyVerticalGrid(GridCells.Adaptive(104.dp), Modifier.fillMaxSize().dragSelect(sstate, { u -> uidIndex[u] ?: -1 }) { i -> list.getOrNull(i)?.uid }, state = sstate, horizontalArrangement = Arrangement.spacedBy(2.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            items(list.size, key = { list[it].uid }) { i ->
                val im = list[i]
                val on = im.uid in sel
                Tile(im, on, sel.isNotEmpty(), { Store.selected = if (on) sel - im.uid else sel + im.uid }, { open(list, i) })
            }
        }
    }
}

@Composable
fun GridScreen(title: String, list: List<Img>, open: (List<Img>, Int) -> Unit, back: (() -> Unit)?, extra: @Composable RowScope.() -> Unit = {}) {
    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
            if (back != null) TextButton(back) { Text("‹") }
            Text(title, Modifier.weight(1f), style = MaterialTheme.typography.titleMedium)
            extra()
            ViewMenuButton()
        }
        if (list.isEmpty()) Text("Chưa có ảnh.", Modifier.padding(16.dp), color = Color.Gray)
        SelGrid(list, open) { uids, clear, select -> LabelActions(uids, clear, select, list) }
    }
}

val CLOTHES = listOf("cloth" to "Dressed", "nude" to "Naked")

/** Lọc Dressed / Naked (PC phân tích bằng CLIP; chỉ là gợi ý), chỉ dùng trong trang từng người. Đếm theo danh sách `images` đang xem. */
@Composable
fun ClothFilterRow(images: List<Img>, selected: String?, onSelect: (String?) -> Unit) {
    if (Store.clothing.isEmpty()) return
    val counts = images.mapNotNull { Store.clothing[it.uid] }.groupingBy { it }.eachCount()
    Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 8.dp, vertical = 4.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        FilterPill("Tất cả", selected == null) { onSelect(null) }
        for ((code, name) in CLOTHES) { val n = counts[code] ?: 0; if (n > 0) FilterPill("$name ($n)", selected == code) { onSelect(if (selected == code) null else code) } }
    }
}

@Composable
fun FilterPill(text: String, selected: Boolean, onClick: () -> Unit) {
    Text(text, Modifier.clip(RoundedCornerShape(18.dp)).background(if (selected) Brass else Color(0x1A000000)).clickable { onClick() }
        .padding(horizontal = 14.dp, vertical = 7.dp), color = if (selected) Color.White else Color(0xFF1B1812), style = MaterialTheme.typography.labelLarge)
}

/** Tất cả ảnh: như trang một người, 5 nút tròn nổi phía trên: ↻ tải lại (✕ khi đang chọn ảnh), Dressed, Naked, All, ⋯. */
@Composable
fun AllPhotos(open: (List<Img>, Int) -> Unit, focus: String? = null, favOnly: Boolean = false, onClassify: (String, String) -> Unit = { _, _ -> }, onAdd: () -> Unit = {}) {
    var cloth by remember { mutableStateOf<String?>(null) }
    var loading by remember { mutableStateOf(false) }
    var msg by remember { mutableStateOf("") }
    var dlg by remember { mutableStateOf("") }
    val scope = rememberCoroutineScope()
    val v = Store.version
    // mới nhất ở trên cùng; ảnh không rõ ngày xuống cuối
    val favLabel = Store.labels.firstOrNull { it.name == "Yêu thích" }?.id
    val sorted = remember(Store.images, Store.labelOf, favOnly, favLabel, if (favOnly) v else 0) {          // chỉ tab Favorite cần tính lại khi thay đổi sao; các tab khác không sắp xếp lại cả thư viện sau mỗi thao tác
        val all = Store.images.sortedByDescending { it.taken }
        if (favOnly) all.filter { favLabel != null && Store.labelOf[it.uid]?.contains(favLabel) == true } else all           // tab Favorite: chỉ những ảnh đã bấm ngôi sao khi xem ảnh
    }
    val clothMap = Store.clothing                                          // đọc trực tiếp: ảnh vừa chuyển loại biến khỏi danh sách ngay lập tức
    val list = if (cloth == null) sorted else sorted.filter { clothMap[it.uid] == cloth }
    val shownUids = remember(list) { list.map { it.uid }.toHashSet() }
    val selecting = Store.selected.any { it in shownUids }               // đang chọn ảnh: Dressed / Naked phân loại luôn ảnh đã chọn
    Box(Modifier.fillMaxSize()) {
        TimelineGrid(list, open, focus, topBarSpace()) { _, _, _ -> }
        if (list.isEmpty()) Text(if (favOnly) "Chưa có ảnh yêu thích. Bấm ngôi sao khi xem ảnh để thêm." else "Chưa có ảnh.", Modifier.padding(top = 80.dp, start = 16.dp), color = Color.Gray)
        if (msg.isNotEmpty()) Text(msg, Modifier.align(Alignment.TopCenter).padding(top = 66.dp).background(Color(0xCC000000), RoundedCornerShape(12.dp)).padding(horizontal = 10.dp, vertical = 4.dp), color = Color.White, style = MaterialTheme.typography.bodySmall)
        TopBar(Modifier.align(Alignment.TopStart),
            left = {
                if (Store.selected.isNotEmpty()) RoundBtn(onClick = { Store.selected = emptySet() }) { BtnIcon("close") }          // chưa chọn ảnh: không có nút nào bên trái (đã bỏ nút tải lại, app tự nhận dữ liệu mới từ PC)
                if (selecting) RoundBtn(onClick = onAdd) { BtnIcon("add") }
            },
            center = {
                ClothPill(cloth, selecting) { c ->
                    if (c != null && selecting) onClassify(c, CLOTHES.first { it.first == c }.second)
                    else cloth = if (c != null && cloth == c) null else c
                }
            },
            right = { RoundBtn(onClick = { dlg = "view" }) { BtnIcon("dots") } })
    }
    if (dlg == "view") ViewSettingsDialog { dlg = "" }
    if (v < 0) Text("")
}

/** Mashup: ảnh chụp kết hợp từ 2 người trở lên, gom theo tổ hợp; chọn một tổ hợp để xem ảnh. */
/** Mashup: chia tab theo SỐ NGƯỜI trong ảnh (2, 3, 4…); mỗi tab chia Dressed / Naked. */
@Composable
fun ComboScreen(open: (List<Img>, Int) -> Unit) {
    val v = Store.version
    val byN = remember(Store.combos) { Store.combos.groupBy { it.names.size }.mapValues { e -> e.value.flatMap { it.uids }.distinct() }.toSortedMap() }
    var n by remember { mutableStateOf<Int?>(null) }
    val cur = if (n != null && byN.containsKey(n)) n else byN.keys.firstOrNull()
    Column(Modifier.fillMaxSize()) {
        if (cur == null) {
            Text("Chưa có ảnh nào chụp chung từ 2 người trở lên (PC tính khi đồng bộ).", Modifier.padding(16.dp), color = Color.Gray)
        } else {
            androidx.compose.foundation.lazy.LazyRow(Modifier.fillMaxWidth().padding(vertical = 6.dp), contentPadding = PaddingValues(horizontal = 8.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                items(byN.keys.toList()) { k -> FilterPill("$k người (" + (byN[k]?.size ?: 0) + ")", k == cur) { n = k } }
                item { ViewMenuButton() }
            }
            val byUid = remember(Store.images) { Store.images.associateBy { it.uid } }
            val imgs = (byN[cur] ?: emptyList()).mapNotNull { byUid[it] }.sortedByDescending { it.taken }
            val groups = listOf(
                "Dressed" to imgs.filter { Store.clothing[it.uid] == "cloth" },
                "Naked" to imgs.filter { Store.clothing[it.uid] == "nude" },
                "Chưa phân loại" to imgs.filter { Store.clothing[it.uid] != "cloth" && Store.clothing[it.uid] != "nude" }
            ).filter { it.second.isNotEmpty() }
            GroupedGrid(groups, open) { _, _, _ -> }
        }
    }
    if (v < 0) Text("")
}

/** Bỏ dấu tiếng Việt và về chữ thường để xếp A-Z. */
fun foldVi(s: String): String =
    java.text.Normalizer.normalize(s.replace('đ', 'd').replace('Đ', 'D'), java.text.Normalizer.Form.NFD).replace(Regex("\\p{Mn}+"), "").lowercase()

/** Chữ cái đầu của họ tên (không dấu); chưa đặt tên hoặc ký tự lạ thì '#'. */
fun letterOf(name: String): String {
    val c = foldVi(name.trim()).firstOrNull { it.isLetterOrDigit() }
    return if (c != null && c in 'a'..'z') c.uppercaseChar().toString() else "#"
}

const val PAGE_SIZE = 50          // mỗi trang Model: lưới 5 cột x 10 hàng

/** Trái tim vẽ bằng nét, nằm đúng giữa vòng tròn. */
@Composable
fun HeartIcon(filled: Boolean, modifier: Modifier = Modifier) {
    androidx.compose.foundation.Canvas(modifier) {
        val w = size.width; val h = size.height
        val path = androidx.compose.ui.graphics.Path().apply {
            moveTo(w * 0.5f, h * 0.92f)
            cubicTo(w * -0.15f, h * 0.45f, w * 0.12f, h * -0.05f, w * 0.5f, h * 0.28f)
            cubicTo(w * 0.88f, h * -0.05f, w * 1.15f, h * 0.45f, w * 0.5f, h * 0.92f)
            close()
        }
        if (filled) drawPath(path, Color(0xFFFF5A6E))
        else drawPath(path, Color.White, style = androidx.compose.ui.graphics.drawscope.Stroke(width = w * 0.11f))
    }
}

/** Ảnh profile do PC chọn và cắt sẵn (từ rốn lên): chỉ việc hiển thị. */
@Composable
fun CoverPhoto(pid: Int, sig: String?, modifier: Modifier) {
    val b by produceState<Bitmap?>(null, pid, sig) { value = Store.cover(pid) }
    Box(modifier.background(Color(0xFF3A3226))) {
        b?.let { Image(it.asImageBitmap(), null, Modifier.fillMaxSize(), contentScale = ContentScale.Crop, alignment = Alignment.TopCenter) }
    }
}

/** Thẻ người: ảnh 3:4 bo góc (cắt từ rốn trở lên), tên và số ảnh ở chân ảnh, trái tim Favorite ở góc trên trái (như bản PC). */
@Composable
fun PersonCard(p: Person, cover: String?, cols: Int, onOpen: (Person) -> Unit, nameFs: Float? = null) {
    val fs = nameFs ?: (if (cols <= 3) 12f else 10f)           // cỡ chữ chung cho cả lưới (tính để tên dài nhất vẫn vừa một dòng)
    val fav = p.id in Store.favPersons
    val pending = Store.suggestionsOf(p.id).isNotEmpty()                      // còn ảnh đề xuất chưa xác nhận: viền vàng đồng mảnh quanh thẻ (đứng yên, không tốn pin)
    androidx.compose.foundation.layout.BoxWithConstraints(Modifier.fillMaxWidth().aspectRatio(0.75f).clip(RoundedCornerShape(9.dp)).background(Color(0xFF3A3226)).clickable { onOpen(p) }
        .then(if (pending) Modifier.border(2.dp, Brass, RoundedCornerShape(9.dp)) else Modifier)) {
        val pc = Store.covers[p.id]
        if (pc != null) {
            CoverPhoto(p.id, pc, Modifier.fillMaxSize())            // ảnh profile do PC chọn tự động và cắt sẵn
        } else if (cover != null) {
            // chưa có ảnh PC chọn: ảnh thu nhỏ đầu tiên, phóng lên để chỉ hiện phần từ rốn trở lên (bám mép trên ảnh)
            Thumb(cover, Modifier.requiredWidth(maxWidth).requiredHeight(maxHeight * 1.7f).align(Alignment.TopStart), Alignment.TopCenter)
        }
        Box(Modifier.align(Alignment.BottomCenter).fillMaxWidth().fillMaxHeight(0.5f)
            .background(androidx.compose.ui.graphics.Brush.verticalGradient(listOf(Color.Transparent, Color(0xD1000000)))))
        Column(Modifier.align(Alignment.BottomStart).padding(start = 3.dp, end = 3.dp, bottom = 3.dp)) {
            Text(p.name.ifEmpty { "Chưa đặt tên" }, Modifier.fillMaxWidth(), color = Color.White, maxLines = 1, softWrap = false, overflow = androidx.compose.ui.text.style.TextOverflow.Visible, fontSize = fs.sp, lineHeight = (fs + 1f).sp, fontWeight = androidx.compose.ui.text.font.FontWeight.Bold)
            Text("${p.n} ảnh", Modifier.padding(top = 1.dp), color = Color(0xCCFFFFFF), fontSize = (fs - 1.5f).sp, lineHeight = (fs - 0.5f).sp)
        }
        Box(Modifier.align(Alignment.TopStart).padding(3.dp).size(18.dp).clip(CircleShape).background(Color(0x66000000)).clickable { Store.toggleFavPerson(p.id) },
            contentAlignment = Alignment.Center) {
            HeartIcon(fav, Modifier.size(10.dp))
        }
    }
}

@Composable
fun PersonGrid(list: List<Person>, covers: Map<Int, String>, cols: Int, onOpen: (Person) -> Unit, header: String? = null, stateKey: String? = null, onZoom: ((Int) -> Unit)? = null) {
    val saved = remember(stateKey) { if (stateKey != null) Store.modelScrollOf(stateKey) else Pair(0, 0) }
    val gs = androidx.compose.foundation.lazy.grid.rememberLazyGridState(saved.first, saved.second)
    LaunchedEffect(gs, stateKey) {                                   // nhớ vị trí cuộn của từng chữ cái
        if (stateKey != null) snapshotFlow { gs.firstVisibleItemIndex to gs.firstVisibleItemScrollOffset }.collectLatest { (i, o) -> delay(300); Store.setModelScroll(stateKey, i, o) }
    }
    // tên mỗi người nằm vừa MỘT dòng và mọi thẻ cùng một cỡ chữ: lấy cỡ lớn nhất mà tên dài nhất trong danh sách vẫn vừa bề ngang thẻ
    val measurer = androidx.compose.ui.text.rememberTextMeasurer()
    val dens = androidx.compose.ui.platform.LocalDensity.current
    val screenW = androidx.compose.ui.platform.LocalConfiguration.current.screenWidthDp
    val cardPx = with(dens) { (((screenW - 12 - 5 * (cols - 1)).toFloat() / cols) - 8f).dp.toPx() }
    val baseFs = when (cols) { 3 -> 12f; 4 -> 10f; else -> 8.5f }
    val nameFs = remember(list, cardPx, baseFs) {
        var widest = 1
        for (p in list) {
            val w = measurer.measure(androidx.compose.ui.text.AnnotatedString(p.name.ifEmpty { "Chưa đặt tên" }), androidx.compose.ui.text.TextStyle(fontSize = baseFs.sp, fontWeight = androidx.compose.ui.text.font.FontWeight.Bold), softWrap = false).size.width
            if (w > widest) widest = w
        }
        minOf(baseFs, baseFs * cardPx / widest).coerceAtLeast(6f)
    }
    // thu phóng đổi số cột: lấy người đầu tiên bên trái đang thấy làm điểm neo, sau khi đổi vẫn nằm đúng chỗ cũ trên màn hình (không bị trôi)
    var lastCols by remember { mutableStateOf(cols) }
    val anchor = remember { arrayOfNulls<Pair<Int, Int>>(1) }
    if (lastCols != cols) {
        val fi = gs.layoutInfo.visibleItemsInfo.firstOrNull { it.key is Int }
        anchor[0] = fi?.let { (it.key as Int) to it.offset.y }
        lastCols = cols
    }
    LaunchedEffect(cols) {
        val a = anchor[0] ?: return@LaunchedEffect
        anchor[0] = null
        val idx = list.indexOfFirst { it.id == a.first }
        if (idx < 0) return@LaunchedEffect
        val gi = idx + (if (header != null) 1 else 0)
        gs.scrollToItem(gi)
        androidx.compose.runtime.withFrameNanos { }
        val y = gs.layoutInfo.visibleItemsInfo.firstOrNull { it.index == gi }?.offset?.y ?: return@LaunchedEffect
        if (y != a.second) gs.dispatchRawDelta((y - a.second).toFloat())
    }
    val colsNow by androidx.compose.runtime.rememberUpdatedState(cols)
    val zoomCb by androidx.compose.runtime.rememberUpdatedState(onZoom)
    val mpz = rememberPinchZoom { st ->                                // giãn = ít người mỗi hàng hơn (thẻ to hơn), chụm = nhiều người mỗi hàng hơn; chỉ 3, 4, 5
        val n = colsNow - st
        if (n < 3 || n > 5 || zoomCb == null) null else { zoomCb?.invoke(n); colsNow.toFloat() / n }
    }
    val zoomMod = Modifier.pinchZoom(mpz)
    LazyVerticalGrid(GridCells.Fixed(cols), Modifier.fillMaxSize().then(zoomMod), state = gs, contentPadding = PaddingValues(6.dp),
        horizontalArrangement = Arrangement.spacedBy(5.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
        if (header != null) item(key = "head", span = { GridItemSpan(maxLineSpan) }) {                 // chữ cái + số lượng người ở đầu danh sách, cuộn lên cùng danh sách
            Text(header, Modifier.fillMaxWidth().padding(start = 4.dp, top = 6.dp, bottom = 2.dp), style = MaterialTheme.typography.titleMedium, color = Brass)
        }
        items(list, key = { it.id }) { p -> PersonCard(p, covers[p.id], cols, onOpen, nameFs) }
    }
}

/** Ảnh đại diện mỗi người: ảnh đầu tiên có người đó (tính một lần cho cả danh sách). */
@Composable
fun rememberCovers(): Map<Int, String> {
    val v = Store.version
    return remember(Store.images, v) {
        val m = HashMap<Int, String>()
        for (im in Store.images) Store.personOf[im.uid]?.forEach { if (!m.containsKey(it)) m[it] = im.uid }
        m
    }
}

/** Model: lưới 4 cột, vuốt lên/xuống để cuộn; vuốt trái/phải để đổi CHỮ CÁI; hàng chữ cái ở trên để nhảy tới chữ. */
@OptIn(androidx.compose.foundation.ExperimentalFoundationApi::class)
@Composable
fun ModelScreen(onOpen: (Person) -> Unit) {
    val v = Store.version
    val favs = Store.favPersons
    val byLetter = remember(Store.persons, v, favs) {
        val sorted = compareBy<Person>({ it.name.isEmpty() }, { if (it.name.isEmpty()) -it.n else 0 }, { foldVi(it.name) }, { -it.n })
        val shown = Store.persons.filter { it.n > 0 }
        val m = LinkedHashMap<String, List<Person>>()
        m["♥"] = shown.filter { it.id in favs }.sortedWith(sorted)                          // trang riêng của những người đã bấm trái tim, đặt ở đầu hàng chữ cái (bên trái chữ A)
        shown.groupBy { letterOf(it.name) }.toSortedMap(compareBy<String>({ it == "#" }, { it })).forEach { (k, vv) -> m[k] = vv.sortedWith(sorted) }
        m
    }
    val keys = remember(byLetter) { byLetter.keys.toList() }
    val covers = rememberCovers()
    val pager = androidx.compose.foundation.pager.rememberPagerState { keys.size.coerceAtLeast(1) }
    val scope = rememberCoroutineScope()
    val cur = keys.getOrNull(pager.currentPage)
    val lstate = androidx.compose.foundation.lazy.rememberLazyListState()
    var started by androidx.compose.runtime.saveable.rememberSaveable { mutableStateOf(false) }
    LaunchedEffect(keys.size) {                                       // lần đầu mở sau khi khởi động: về đúng chữ cái đã xem lần trước (chưa có thì chữ cái đầu tiên; trang trái tim nằm bên trái)
        if (!started && keys.size > 1) { pager.scrollToPage(keys.indexOf(Store.modelLetter).takeIf { it >= 0 } ?: 1); started = true }
    }
    LaunchedEffect(pager.currentPage, started) { if (started) keys.getOrNull(pager.currentPage)?.let { Store.modelLetter = it } }
    LaunchedEffect(pager.currentPage) { if (keys.isNotEmpty()) lstate.animateScrollToItem((pager.currentPage - 2).coerceAtLeast(0)) }
    Column(Modifier.fillMaxSize()) {
        androidx.compose.foundation.lazy.LazyRow(Modifier.fillMaxWidth().padding(vertical = 4.dp), state = lstate, contentPadding = PaddingValues(horizontal = 8.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            items(keys) { l ->
                if (l == "♥") Box(Modifier.size(34.dp).clip(CircleShape).background(if (l == cur) Brass else Color(0x1A000000)).clickable { scope.launch { pager.animateScrollToPage(keys.indexOf(l)) } }, contentAlignment = Alignment.Center) {
                    HeartIcon(true, Modifier.size(16.dp))                 // nút trái tim nằm trong hình tròn, trước chữ A
                } else FilterPill(l, l == cur) { scope.launch { pager.animateScrollToPage(keys.indexOf(l)) } }
            }
        }
        if (keys.size <= 1) Text("Chưa có ai trong thư viện.", Modifier.padding(16.dp), color = Color.Gray)
        androidx.compose.foundation.pager.HorizontalPager(pager, Modifier.weight(1f).fillMaxWidth(), key = { keys.getOrNull(it) ?: "-" }) { pg ->
            val lk = keys.getOrNull(pg)
            val people = byLetter[lk] ?: emptyList()
            if (lk == "♥" && people.isEmpty()) Text("Chưa có ai trong danh sách yêu thích. Bấm hình trái tim trên thẻ người để thêm.", Modifier.padding(16.dp), color = Color.Gray)
            else PersonGrid(people, covers, Store.modelCols, onOpen, if (lk != null) (if (lk == "♥") "♥  ·  ${people.size} người" else "$lk  ·  ${people.size} người") else null, lk) { Store.setModelColumns(it) }       // Model: 3–5 cột, chụm / giãn để đổi
        }
    }
    if (v < 0) Text("")
}

/** Cài đặt: trang mở đầu, không có ảnh nào. */
@Composable
fun SettingsScreen() {
    val ctx = androidx.compose.ui.platform.LocalContext.current
    val scope = rememberCoroutineScope()
    var msg by remember { mutableStateOf("") }
    var loading by remember { mutableStateOf(false) }
    val ver = remember { try { ctx.packageManager.getPackageInfo(ctx.packageName, 0).versionName ?: "" } catch (e: Exception) { "" } }
    Column(Modifier.fillMaxSize().padding(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("Cài đặt", style = MaterialTheme.typography.headlineSmall)
        Text("Phiên bản: $ver", color = Color.Gray)
        Button({
            loading = true; msg = ""
            scope.launch { try { Store.reload { msg = it }; msg = "Đã cập nhật từ máy tính" } catch (e: Exception) { msg = e.message ?: "Lỗi" } finally { loading = false } }
        }, enabled = !loading) { Text("Tải lại dữ liệu từ máy tính") }
        if (loading) CircularProgressIndicator()
        if (msg.isNotEmpty()) Text(msg, color = Color.Gray)
    }
}

@Composable
fun PersonScreen(p: Person, open: (List<Img>, Int) -> Unit, onClassify: (String, String) -> Unit, onAdd: () -> Unit, onRemove: () -> Unit, onSuggest: () -> Unit, back: () -> Unit) {
    val v = Store.version
    var dlg by remember { mutableStateOf("") }
    val scope = rememberCoroutineScope()
    val all = remember(Store.images, v) { Store.images.filter { Store.personOf[it.uid]?.contains(p.id) == true }.sortedByDescending { it.taken } }
    var cloth by remember(p.id) { mutableStateOf<String?>(if (all.any { Store.clothing[it.uid] == "cloth" }) "cloth" else null) }      // mặc định mở thẻ Dressed (nếu người đó chưa có ảnh Dressed thì mở All)
    val clothMap = Store.clothing                                          // đọc trực tiếp: ảnh vừa chuyển loại biến khỏi danh sách ngay lập tức
    val list = if (cloth == null) all else all.filter { clothMap[it.uid] == cloth }
    val shownUids = remember(list) { list.map { it.uid }.toHashSet() }
    val selecting = Store.selected.any { it in shownUids }               // đang chọn ảnh trong danh sách này: Dressed / Naked phân loại luôn ảnh đã chọn
    // trang xem ảnh của một người: KHÔNG có tiêu đề tên (bên ngoài đã có), ảnh chiếm trọn màn hình; các nút tròn nổi phía trên ảnh
    Box(Modifier.fillMaxSize()) {
        val acts: @Composable RowScope.(List<String>, () -> Unit, (Set<String>) -> Unit) -> Unit = { _, _, _ -> }
        if (cloth == null) {
            // Tất cả: chia cụm Dressed / Naked / Chưa phân loại, cụm trống tự ẩn
            val groups = listOf(
                "Dressed" to all.filter { clothMap[it.uid] == "cloth" },
                "Naked" to all.filter { clothMap[it.uid] == "nude" },
                "Chưa phân loại" to all.filter { clothMap[it.uid] != "cloth" && clothMap[it.uid] != "nude" }
            ).filter { it.second.isNotEmpty() }
            GroupedGrid(groups, open, topBarSpace(), acts)
        } else {
            TimelineGrid(list, open, null, topBarSpace(), acts)
        }
        if (all.isEmpty()) Text("Chưa có ảnh.", Modifier.padding(top = 80.dp, start = 16.dp), color = Color.Gray)
        val sugg = Store.suggestionsOf(p.id).size
        if (sugg > 0 && !selecting) {                                  // nút hình người ở giữa phía dưới: ảnh app chưa chắc chắn là của người này, bấm để xác nhận đúng / sai
            val d = androidx.compose.ui.platform.LocalConfiguration.current.screenWidthDp.dp / 8.5f
            androidx.compose.runtime.CompositionLocalProvider(LocalBtn provides d) {
                Box(Modifier.align(Alignment.BottomCenter).padding(bottom = 18.dp)) {
                    RoundBtn(onClick = onSuggest) { BtnIcon("person") }
                    Box(Modifier.align(Alignment.TopEnd).offset(x = 6.dp, y = (-4).dp).then(Modifier.widthIn(min = 18.dp).heightIn(min = 18.dp)).clip(CircleShape).background(Brass), contentAlignment = Alignment.Center) {
                        Text("$sugg", color = Color.White, fontSize = 10.sp, modifier = Modifier.padding(horizontal = 4.dp))
                    }
                }
            }
        }
        // hàng nút phía trên: ← (✕ khi đang chọn) và Thêm vào tên ở góc trái; ô dài Dressed | Naked | All ở giữa; Loại khỏi danh sách và ⋯ ở góc phải
        TopBar(Modifier.align(Alignment.TopStart),
            left = {
                if (Store.selected.isNotEmpty()) RoundBtn(onClick = { Store.selected = emptySet() }) { BtnIcon("close") }
                else RoundBtn(onClick = back) { BtnIcon("back") }
                if (selecting) RoundBtn(onClick = onAdd) { BtnIcon("add") }
            },
            center = {
                ClothPill(cloth, selecting) { c ->
                    if (c != null && selecting) onClassify(c, CLOTHES.first { it.first == c }.second)      // đang chọn ảnh: chuyển ảnh đã chọn sang loại này
                    else cloth = if (c != null && cloth == c) null else c                                  // không chọn ảnh: chuyển thẻ loại (bấm lần nữa để về All)
                }
            },
            right = {
                if (selecting) RoundBtn(onClick = onRemove) { BtnIcon("remove") }
                RoundBtn(onClick = { dlg = "view" }) { BtnIcon("dots") }           // ⋯: mở thẳng các lựa chọn chế độ xem ảnh
            })
    }
    if (dlg == "view") ViewSettingsDialog { dlg = "" }
    if (v < 0) Text("")
}

/** Trang đề xuất: ảnh app chưa chắc chắn là của người này (như bên PC). Chọn ảnh rồi bấm tick = đúng người, người+ = thêm vào tên khác, người− = không phải người này; ✕ bỏ chọn / quay lại, Enter tới vị trí ảnh. */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun SuggestScreen(p: Person, open: (List<Img>, Int) -> Unit, onAccept: () -> Unit, onAdd: () -> Unit, onReject: () -> Unit, onLocate: () -> Unit, onClassify: (String, String) -> Unit, back: () -> Unit) {
    val v = Store.version
    val byUid = remember(Store.images) { Store.images.associateBy { it.uid } }
    val sugg = Store.suggestionsOf(p.id)
    val items = sugg.mapNotNull { (u, sc) -> byUid[u]?.let { it to sc } }
    val list = items.map { it.first }
    val score = items.associate { it.first.uid to it.second }
    val sel = Store.selected
    val state = rememberLazyGridState()
    var viewDlg by remember { mutableStateOf(false) }
    LaunchedEffect(list.map { it.uid }) { Store.pool = list }
    val uidIndex = remember(list.map { it.uid }) { HashMap<String, Int>().also { m -> list.forEachIndexed { i, im -> m[im.uid] = i + 1 } } }        // +1: ô tiêu đề nằm đầu lưới
    Box(Modifier.fillMaxSize()) {
        LazyVerticalGrid(GridCells.Fixed(3), Modifier.fillMaxSize().dragSelect(state, { u -> uidIndex[u] ?: -1 }) { i -> list.getOrNull(i - 1)?.uid },
            state = state, contentPadding = PaddingValues(top = topBarSpace()), horizontalArrangement = Arrangement.spacedBy(2.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            item(span = { GridItemSpan(maxLineSpan) }, key = "head") {
                Text("Có thể là ${p.name.ifEmpty { "người này" }} · ${list.size} ảnh", Modifier.fillMaxWidth().padding(start = 12.dp, top = 6.dp, bottom = 6.dp), style = MaterialTheme.typography.titleSmall, color = Brass)
            }
            items(list.size, key = { list[it].uid }) { i ->
                val im = list[i]
                val on = im.uid in sel
                Box {
                    Tile(im, on, sel.isNotEmpty(), { Store.selected = if (on) sel - im.uid else sel + im.uid }, { open(list, i) })
                    Text("${((score[im.uid] ?: 0f) * 100).toInt()}%", Modifier.align(Alignment.BottomEnd).padding(5.dp).background(Color(0x99000000), RoundedCornerShape(6.dp)).padding(horizontal = 5.dp, vertical = 1.dp),
                        color = Color(0xFFFFD05A), fontSize = 10.sp)
                }
            }
        }
        if (list.isEmpty()) Text("Không còn ảnh nào cần xác nhận.", Modifier.padding(top = topBarSpace() + 30.dp, start = 16.dp), color = Color.Gray)
        val selecting = Store.selected.any { it in uidIndex }                  // chưa chọn ảnh: chỉ hiện hai nút ngoài cùng (✕ và Enter); chọn ảnh rồi mới hiện các nút lệnh còn lại
        TopBar(Modifier.align(Alignment.TopStart),
            left = {
                RoundBtn(onClick = { if (Store.selected.isNotEmpty()) Store.selected = emptySet() else back() }) { BtnIcon("close") }
                if (selecting) RoundBtn(onClick = onAdd) { BtnIcon("add") }
            },
            center = {
                if (selecting) ClothPill(null, true, thirdKind = "tick", onThird = onAccept) { c -> if (c != null) onClassify(c, CLOTHES.first { it.first == c }.second) }
            },
            right = {
                if (selecting) {
                    RoundBtn(onClick = onReject) { BtnIcon("remove") }
                    RoundBtn(onClick = onLocate) { BtnIcon("enter") }                 // đã chọn ảnh: Enter tới vị trí ảnh
                } else RoundBtn(onClick = { viewDlg = true }) { BtnIcon("dots") }      // chưa chọn ảnh: nút ⋯ (chế độ xem ảnh) như trang người
            })
        if (viewDlg) ViewSettingsDialog { viewDlg = false }
    }
    if (v < 0) Text("")
}

@Composable
fun LabelsScreen(onOpen: (Label) -> Unit) {
    val v = Store.version
    Column(Modifier.fillMaxSize()) {
        Text("Nhãn", Modifier.padding(12.dp), style = MaterialTheme.typography.titleMedium)
        LazyColumn(Modifier.fillMaxSize()) {
            items(Store.labels, key = { it.id }) { l ->
                val n = Store.labelOf.values.count { it.contains(l.id) }
                Row(Modifier.fillMaxWidth().clickable { onOpen(l) }.padding(16.dp)) { Text(l.name, Modifier.weight(1f)); Text("$n", color = Color.Gray) }
            }
        }
    }
    if (v < 0) Text("")
}

@Composable
fun LabelScreen(l: Label, open: (List<Img>, Int) -> Unit, back: () -> Unit) {
    val v = Store.version
    var dlg by remember { mutableStateOf("") }
    var name by remember { mutableStateOf(l.name) }
    val scope = rememberCoroutineScope()
    val cur = Store.labels.firstOrNull { it.id == l.id }
    if (cur == null) { back(); return }
    var sug by remember { mutableStateOf<List<Pair<Img, Float>>?>(null) }
    var note by remember { mutableStateOf("") }
    val list = Store.images.filter { Store.labelOf[it.uid]?.contains(l.id) == true }
    val sugList = sug
    if (sugList == null) {
        GridScreen("${cur.name} (${list.size})", list, open, back) {
            TextButton({
                scope.launch {
                    if (!Store.ensureClip()) note = "Chưa có dữ liệu nhận diện nội dung ảnh. Trên máy tính bấm Đồng bộ ngay, chờ Drive tải lên, rồi bấm ↻ tải lại."
                    else { val r = Store.suggestFor(cur); sug = r; if (r.isEmpty()) note = "Chưa có ảnh nào giống ảnh trong nhãn này (cần ít nhất vài ảnh mẫu)." }
                }
            }) { Text("Gợi ý ảnh giống") }
            TextButton({ dlg = "rename" }) { Text("Đổi tên") }
            TextButton({ dlg = "delete" }) { Text("Xóa nhãn") }
        }
    } else {
        val imgs = sugList.map { it.first }
        Column(Modifier.fillMaxSize()) {
            Row(Modifier.fillMaxWidth().padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                TextButton({ sug = null }) { Text("‹") }
                Text("Gợi ý cho “${cur.name}” (${imgs.size})", Modifier.weight(1f), style = MaterialTheme.typography.titleMedium)
            }
            Text("Chọn các ảnh đúng (chạm vòng tròn ở góc ảnh), rồi bấm “Thêm vào nhãn”. Ảnh xếp từ giống nhất đến ít giống hơn.", Modifier.padding(horizontal = 12.dp), color = Color.Gray)
            SelGrid(imgs, open) { uids, clear, select ->
                TextButton({ select(sugList.filter { it.second >= 0.85f }.map { it.first.uid }.toSet()) }) { Text("Chọn từ 85%") }
                TextButton({
                    scope.launch {
                        try { Store.labelAdd(uids, cur.name) } catch (e: Exception) { }
                        clear()
                        sug = Store.suggestFor(cur)
                    }
                }) { Text("Thêm ${uids.size} ảnh vào nhãn") }
            }
        }
    }
    if (note.isNotEmpty()) AlertDialog(onDismissRequest = { note = "" }, confirmButton = { TextButton({ note = "" }) { Text("Đóng") } }, title = { Text("Gợi ý ảnh giống") }, text = { Text(note) })
    if (dlg == "rename") AlertDialog(onDismissRequest = { dlg = "" }, title = { Text("Đổi tên nhãn") },
        text = { OutlinedTextField(name, { name = it }, singleLine = true) },
        confirmButton = { TextButton({ dlg = ""; scope.launch { try { Store.labelRename(cur, name) } catch (e: Exception) { } } }) { Text("Lưu") } },
        dismissButton = { TextButton({ dlg = "" }) { Text("Hủy") } })
    if (dlg == "delete") AlertDialog(onDismissRequest = { dlg = "" }, title = { Text("Xóa nhãn?") }, text = { Text("Ảnh không bị xóa, chỉ gỡ nhãn “${cur.name}”.") },
        confirmButton = { TextButton({ dlg = ""; scope.launch { try { Store.labelDelete(cur) } catch (e: Exception) { }; back() } }) { Text("Xóa") } },
        dismissButton = { TextButton({ dlg = "" }) { Text("Hủy") } })
    if (v < 0) Text("")
}

@Composable
fun SearchScreen(open: (List<Img>, Int) -> Unit) {
    var q by remember { mutableStateOf("") }
    val t = q.trim().lowercase()
    val res = if (t.isEmpty()) emptyList() else Store.images.filter { im ->
        im.name.lowercase().contains(t) || im.taken.contains(t) ||
            (Store.personOf[im.uid] ?: emptyList<Int>()).any { id -> Store.persons.firstOrNull { it.id == id }?.name?.lowercase()?.contains(t) == true } ||
            (Store.labelOf[im.uid] ?: emptySet<Int>()).any { id -> Store.labels.firstOrNull { it.id == id }?.name?.lowercase()?.contains(t) == true }
    }
    Column(Modifier.fillMaxSize()) {
        OutlinedTextField(q, { q = it }, label = { Text("Tìm theo tên người, nhãn, tên tệp, ngày (2024-05)…") }, singleLine = true, modifier = Modifier.fillMaxWidth().padding(12.dp))
        SelGrid(res, open) { uids, clear, select -> LabelActions(uids, clear, select, res) }
    }
}

@Composable
fun ViewerScreen(listIn: List<Img>, start: Int, fromPerson: Person?, fromSuggest: Person?, onPerson: (Person) -> Unit, onLocate: (Img) -> Unit, close: () -> Unit) {
    var removed by remember { mutableStateOf(setOf<String>()) }       // ảnh vừa loại khỏi danh sách: biến mất khỏi dải xem
    // danh sách đang xem là một nhóm đồng loại (ví dụ cả danh sách là Dressed): phân loại ảnh sang loại khác thì ảnh rời nhóm, biến khỏi dải xem và chuyển sang ảnh kế tiếp
    val listClasses = remember(listIn) { listIn.map { Store.clothing[it.uid] }.distinct() }
    val homogeneous = listClasses.size == 1
    val listClass = listClasses.firstOrNull()
    var clothUndo by remember { mutableStateOf<Pair<String, String?>?>(null) }                  // (mã ảnh, loại trước đó) để hoàn tác lần phân loại gần nhất
    var acceptedSuggest by remember { mutableStateOf(false) }        // lần xử lý gần nhất là xác nhận đúng người (hoàn tác: bỏ khỏi người đó và đưa về đề xuất)
    var removedSuggest by remember { mutableStateOf(false) }          // lần loại gần nhất là loại khỏi đề xuất (hoàn tác bằng guessRestore)
    var lastRemoved by remember { mutableStateOf<Pair<Person, String>?>(null) }     // để có nút Hoàn tác
    val list = remember(listIn, removed) { listIn.filter { it.uid !in removed } }
    val pager = rememberPagerState(initialPage = start.coerceIn(0, (listIn.size - 1).coerceAtLeast(0))) { list.size }
    var zoomed by remember { mutableStateOf(false) }
    var info by remember { mutableStateOf(false) }
    var pickDlg by remember { mutableStateOf(false) }
    var playing by remember { mutableStateOf(false) }          // trình chiếu tự động, mỗi ảnh 3 giây
    var chrome by remember { mutableStateOf(true) }          // chạm một lần vào ảnh để ẩn/hiện công cụ và thông tin
    val scope = rememberCoroutineScope()
    if (list.isEmpty()) { LaunchedEffect(Unit) { close() }; return }
    val cur = list[pager.currentPage.coerceIn(0, list.size - 1)]
    val closeAll = { Store.focus(cur.uid); close() }                 // thoát xem ảnh: danh sách cuộn tới ảnh vừa xem
    EdgeBack(true) { closeAll() }
    val v = Store.version
    var note by remember { mutableStateOf("") }
    LaunchedEffect(pager.currentPage) { note = "" }
    // Tải trước theo thứ tự ưu tiên, MỖI LẦN MỘT ẢNH (không tải dàn trải): ảnh đang xem trước, xong mới tới hai ảnh liền kề (theo hướng vuốt rồi ngược lại),
    // rồi ảnh kế tiếp nữa, rồi ảnh nữa theo hướng đang chuyển. Đổi ảnh thì hàng đợi tính lại từ ảnh mới.
    androidx.compose.runtime.DisposableEffect(Unit) {
        Store.viewerActive = true
        onDispose { Store.viewerActive = false }
    }
    var lastPage by remember { mutableStateOf(start) }
    LaunchedEffect(pager.currentPage, list.size) {
        val cp = pager.currentPage
        val dir = if (cp < lastPage) -1 else 1
        lastPage = cp
        val order = listOf(cp + dir, cp - dir, cp + 2 * dir, cp + 3 * dir)
        val curUid = list.getOrNull(cp)?.uid ?: return@LaunchedEffect
        var waited = 0
        while (waited < 60000 && !Store.originalReady(curUid)) { delay(100); waited += 100 }       // chờ ảnh đang xem xong đã
        for (j in order) if (j in list.indices) { try { Store.original(list[j].uid) } catch (e: Exception) { } }
    }
    // ẩn luôn thanh trạng thái và thanh điều hướng khi đang xem ảnh toàn màn hình
    val view = androidx.compose.ui.platform.LocalView.current
    // Chỉ khởi động lại khi bật/tắt phát. (Trước đây khóa theo cả trang hiện tại nên khi lướt qua nửa ảnh, hiệu ứng bị hủy và dừng giữa ranh giới hai ảnh.)
    LaunchedEffect(playing) {
        while (playing) {
            delay(3000)
            if (zoomed) continue                                   // đang phóng to: chờ người xem
            if (pager.currentPage < list.size - 1) pager.animateScrollToPage(pager.currentPage + 1) else playing = false
        }
    }
    androidx.compose.runtime.DisposableEffect(playing) {
        view.keepScreenOn = playing                               // giữ màn hình sáng khi đang trình chiếu
        onDispose { view.keepScreenOn = false }
    }
    androidx.compose.runtime.DisposableEffect(chrome) {
        val w = (view.context as? Activity)?.window
        val c = w?.let { androidx.core.view.WindowCompat.getInsetsController(it, view) }
        c?.systemBarsBehavior = androidx.core.view.WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        if (chrome) c?.show(androidx.core.view.WindowInsetsCompat.Type.systemBars()) else c?.hide(androidx.core.view.WindowInsetsCompat.Type.systemBars())
        onDispose { c?.show(androidx.core.view.WindowInsetsCompat.Type.systemBars()) }
    }
    Box(Modifier.fillMaxSize().background(Color(0xFF0C0A08))) {
        HorizontalPager(pager, Modifier.fillMaxSize(), userScrollEnabled = !zoomed, key = { list[it].uid }) { page ->
            ZoomImage(list[page].uid, { chrome = !chrome }) { zoomed = it }
        }
        if (chrome) {
            // phía trên: một hàng nút giống hệt hàng nút ngoài danh sách ảnh — ✕ và Thêm vào tên ở góc trái, ô dài Dressed | Naked | All ở giữa,
            // Loại khỏi danh sách (khi mở từ trang một người) và Tới vị trí (phím Enter, thay chỗ nút ⋯) ở góc phải. Áp dụng cho ảnh đang xem.
            val curCloth = Store.clothing[cur.uid]
            if (fromSuggest != null) {
                // xem từ trang đề xuất: hàng nút giống hệt trang đề xuất — ✕ trái, ba nút tròn giữa (tick đúng người, người+ thêm vào tên, người− không phải người này), Enter phải
                TopBar(Modifier.align(Alignment.TopCenter),
                    left = { RoundBtn(onClick = closeAll) { BtnIcon("close") } },
                    center = {
                        val d = LocalBtn.current
                        Row(horizontalArrangement = Arrangement.spacedBy(d * 0.25f)) {
                            RoundBtn(onClick = {
                                scope.launch {
                                    removed = removed + cur.uid; lastRemoved = fromSuggest to cur.uid
                                    try { Store.guessAccept(fromSuggest, listOf(cur.uid)); removedSuggest = false; acceptedSuggest = true; note = "Đã xác nhận đúng" }
                                    catch (e: Exception) { note = "Không xác nhận được: ${e.message}" }
                                }
                            }) { BtnIcon("tick") }
                            RoundBtn(onClick = { pickDlg = true }) { BtnIcon("add") }
                            RoundBtn(onClick = {
                                scope.launch {
                                    try { Store.guessReject(fromSuggest, listOf(cur.uid)); removed = removed + cur.uid; lastRemoved = fromSuggest to cur.uid; removedSuggest = true; acceptedSuggest = false; note = "Đã loại khỏi đề xuất" }
                                    catch (e: Exception) { note = "Không loại được: ${e.message}" }
                                }
                            }) { BtnIcon("remove") }
                        }
                    },
                    right = { RoundBtn(onClick = { onLocate(cur) }) { BtnIcon("enter") } })
            } else
            TopBar(Modifier.align(Alignment.TopCenter),
                left = {
                    RoundBtn(onClick = closeAll) { BtnIcon("close") }
                    RoundBtn(onClick = { pickDlg = true }) { BtnIcon("add") }
                },
                center = {
                    // khung xem ảnh: ô dài chỉ có Dressed | Naked (rộng 2 hình tròn); ngôi sao Yêu thích nằm ở góc dưới bên phải, cùng hàng với tên model
                    ClothPill(curCloth, false, showThird = false) { c ->
                        scope.launch {
                            try {
                                if (c != null) {
                                    val prev = Store.clothing[cur.uid]
                                    val u = cur.uid
                                    if (c != prev) { removed = removed + u; clothUndo = u to prev }          // đổi loại: chuyển sang ảnh kế tiếp NGAY, không chờ xử lý (Hoàn tác để khôi phục)
                                    note = "Đã chuyển sang ${CLOTHES.first { it.first == c }.second}"
                                    try { Store.setCloth(listOf(u), c) } catch (e: Exception) { removed = removed - u; clothUndo = null; note = "Không phân loại được: ${e.message}" }
                                }
                            } catch (e: Exception) { note = "Không phân loại được: ${e.message}" }
                        }
                    }
                },
                right = {
                    if (fromPerson != null) RoundBtn(onClick = {
                        scope.launch {
                            try { Store.personRemove(fromPerson, listOf(cur.uid)); removed = removed + cur.uid; lastRemoved = fromPerson to cur.uid; removedSuggest = false; note = "Đã loại khỏi nhóm" }
                            catch (e: Exception) { note = "Không loại được: ${e.message}" }
                        }
                    }) { BtnIcon("remove") }
                    else if (fromSuggest != null) RoundBtn(onClick = {                       // xem từ trang đề xuất: người − = không phải người này, ảnh hết là đề xuất
                        scope.launch {
                            try { Store.guessReject(fromSuggest, listOf(cur.uid)); removed = removed + cur.uid; lastRemoved = fromSuggest to cur.uid; removedSuggest = true; note = "Đã loại khỏi đề xuất" }
                            catch (e: Exception) { note = "Không loại được: ${e.message}" }
                        }
                    }) { BtnIcon("remove") }
                    RoundBtn(onClick = { onLocate(cur) }) { BtnIcon("enter") }
                })
            val labs = Store.labelsOn(listOf(cur.uid)).map { it.first.name }.filter { it != "Yêu thích" }      // ngôi sao đã thể hiện ở nút sao, không ghi lại thành chữ "Nhãn: Yêu thích"
            // phía dưới gọn: Name (đầy đủ, vuốt ngang nếu dài) rồi dòng ngày chụp · cỡ ảnh ở bên trái, số thứ tự ảnh ở góc phải
            Column(Modifier.fillMaxWidth().background(Color(0x99000000)).padding(horizontal = 12.dp, vertical = 6.dp).align(Alignment.BottomCenter)) {
                val ppl = (Store.personOf[cur.uid] ?: emptyList<Int>()).mapNotNull { id -> Store.persons.firstOrNull { it.id == id } }
                val isFav = Store.isFav(cur.uid)
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Row(Modifier.weight(1f).horizontalScroll(rememberScrollState()), verticalAlignment = Alignment.CenterVertically) {
                        if (ppl.isNotEmpty()) Text("Name: ", color = Color.White, softWrap = false)
                        ppl.forEachIndexed { k, pp ->
                            if (k > 0) Text(" ", color = Color.White, softWrap = false, style = MaterialTheme.typography.bodyMedium)          // giữa các tên chỉ một khoảng trắng bằng một ký tự cách, không gạch chân
                            Text(pp.name.ifEmpty { "Chưa đặt tên" }, Modifier.clickable { onPerson(pp) }.padding(vertical = 4.dp), color = Color(0xFFE5C07B), softWrap = false,        // gạch chân đúng chữ của tên, không dính dấu cách
                                style = MaterialTheme.typography.bodyMedium.copy(textDecoration = androidx.compose.ui.text.style.TextDecoration.Underline))
                        }
                    }
                    // ngôi sao Yêu thích: chỉ hình ngôi sao, không khung; được chọn thì vàng và sáng lên
                    Text(if (isFav) "★" else "☆", Modifier.clickable { scope.launch { try { Store.toggleFav(cur.uid) } catch (e: Exception) { } } }.padding(start = 12.dp, top = 2.dp, bottom = 2.dp),
                        color = if (isFav) Color(0xFFFFD05A) else Color.White, fontSize = 24.sp,
                        style = androidx.compose.ui.text.TextStyle(shadow = if (isFav) androidx.compose.ui.graphics.Shadow(Color(0xCCFFD05A), Offset.Zero, 18f) else null))
                }
                if (labs.isNotEmpty()) Text("Nhãn: " + labs.joinToString(", "), color = Color.White, style = MaterialTheme.typography.bodySmall)
                if (note.isNotEmpty() || lastRemoved != null || clothUndo != null) Row(verticalAlignment = Alignment.CenterVertically) {
                    if (note.isNotEmpty()) Text(note, maxLines = 1, color = Color(0xFFFFB4A8), style = MaterialTheme.typography.bodySmall)
                    clothUndo?.let { (uid, prev) ->
                        Text("Hoàn tác", Modifier.clickable { scope.launch { try { if (prev == null) Store.clearCloth(listOf(uid)) else Store.setCloth(listOf(uid), prev); removed = removed - uid; clothUndo = null; note = "Đã hoàn tác" } catch (e: Exception) { note = "Không hoàn tác được: ${e.message}" } } }.padding(start = 12.dp, top = 2.dp, bottom = 2.dp), color = Color(0xFFE5C07B), style = MaterialTheme.typography.bodySmall)
                    }
                    lastRemoved?.let { (pp, uid) ->
                        Text("Hoàn tác", Modifier.clickable { scope.launch { try { if (acceptedSuggest) { Store.personRemove(pp, listOf(uid)); Store.guessRestore(pp, listOf(uid)) } else if (removedSuggest) Store.guessRestore(pp, listOf(uid)) else Store.personRestore(pp, listOf(uid)); removed = removed - uid; lastRemoved = null; note = "Đã hoàn tác" } catch (e: Exception) { note = "Không hoàn tác được: ${e.message}" } } }.padding(start = 12.dp, top = 2.dp, bottom = 2.dp), color = Color(0xFFE5C07B), style = MaterialTheme.typography.bodySmall)
                    }
                }
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Text(listOf(cur.taken.take(10), "${cur.w} × ${cur.h}").filter { it.isNotBlank() && it != "0 × 0" }.joinToString(" · "), Modifier.weight(1f), color = Color(0xFFC9A66B), style = MaterialTheme.typography.bodySmall)
                    Text("${pager.currentPage + 1} / ${list.size}", color = Color.White, style = MaterialTheme.typography.bodySmall, maxLines = 1)
                    Text("ⓘ", Modifier.clickable { info = true }.padding(start = 12.dp, top = 2.dp, bottom = 2.dp), color = Color.White, fontSize = 14.sp)
                }
            }
        }
    }
    if (pickDlg) PersonPickDialog({ pk ->
        pickDlg = false
        scope.launch { try { Store.personAdd(pk, listOf(cur.uid)); note = "Đã thêm vào ${pk.name.ifEmpty { "Chưa đặt tên" }}"; if (fromSuggest != null) { Store.guessReject(fromSuggest, listOf(cur.uid)); removed = removed + cur.uid } } catch (e: Exception) { note = "Không thêm được: ${e.message}" } }
    }, { nm ->
        pickDlg = false
        scope.launch { try { Store.personCreate(nm, listOf(cur.uid)); note = "Đã tạo “${nm.trim()}” và thêm ảnh này"; if (fromSuggest != null) { Store.guessReject(fromSuggest, listOf(cur.uid)); removed = removed + cur.uid } } catch (e: Exception) { note = "Không tạo được: ${e.message}" } }
    }, { pickDlg = false })
    if (info) {
        val people = (Store.personOf[cur.uid] ?: emptyList<Int>()).mapNotNull { id -> Store.persons.firstOrNull { it.id == id }?.name?.ifEmpty { "Chưa đặt tên" } }
        val labs = Store.labelsOn(listOf(cur.uid)).map { it.first.name }
        val appCtx = androidx.compose.ui.platform.LocalContext.current
        var saveMsg by remember(cur.uid) { mutableStateOf("") }
        AlertDialog(onDismissRequest = { info = false }, confirmButton = { TextButton({ info = false }) { Text("Đóng") } },
            dismissButton = {
                if (cur.orig) TextButton({
                    saveMsg = "Đang lưu…"
                    scope.launch { saveMsg = try { "Đã lưu nguyên bản vào " + Store.saveOriginal(appCtx, cur) } catch (e: Exception) { "Không lưu được: ${e.message}" } }
                }) { Text("Lưu ảnh gốc vào máy") }
            }, title = { Text("Thông tin") },
            text = { Text((if (saveMsg.isNotEmpty()) saveMsg + "\n\n" else "") + "Tên: ${cur.name}\nNgày chụp: ${cur.taken.take(16)}\nKích thước: ${cur.w} × ${cur.h}\nẢnh gốc trên Drive: ${if (cur.orig) "có" else "không (đang xem ảnh nhỏ)"}\nName: ${people.joinToString(", ").ifEmpty { "—" }}\nNhãn: ${labs.joinToString(", ").ifEmpty { "—" }}") })
    }
    if (v < 0) Text("")
}

/** Lưới ảnh chia cụm có tiêu đề (cụm trống không hiện). Chọn nhiều ảnh như các lưới khác; mở ảnh thì xem theo thứ tự các cụm. */
@Composable
fun GroupedGrid(groups: List<Pair<String, List<Img>>>, open: (List<Img>, Int) -> Unit, topPad: androidx.compose.ui.unit.Dp = 0.dp, actions: @Composable RowScope.(List<String>, () -> Unit, (Set<String>) -> Unit) -> Unit) {
    val sel = Store.selected
    val flat = remember(groups) { groups.flatMap { it.second } }
    LaunchedEffect(flat) { Store.pool = flat }
    val gfit = Store.layout == "fit"
    val gcols = if (gfit) 120 else if (Store.layout == "month") 5 else 3
    val gw = androidx.compose.ui.platform.LocalConfiguration.current.screenWidthDp.toFloat()
    val gsig = groups.fold(0) { h, g -> g.second.fold(h * 31 + g.first.hashCode()) { x, im -> x * 31 + im.uid.hashCode() } }
    val entries = remember(gsig, gfit, gw) {
        val out = ArrayList<Entry>()
        var pos = 0
        for ((name, imgs) in groups) {
            out.add(Entry.Header("g:$name", "$name · ${imgs.size} ảnh"))
            val jr = if (gfit) justifyRows(imgs, gw) else null
            imgs.forEachIndexed { k, im -> out.add(if (jr != null) Entry.Photo(im, pos, jr[k].first, jr[k].second) else Entry.Photo(im, pos)); pos++ }
        }
        out
    }
    val gstate = rememberLazyGridState()
    KeepAnchor(gstate, entries)
    val gpz = rememberPinchZoom { stepLayout(it) }
    LayoutAnchor(gstate, entries, gpz)
    val uidIndex = remember(entries) { HashMap<String, Int>().also { m -> entries.forEachIndexed { i, e -> if (e is Entry.Photo) m[e.img.uid] = i } } }
    LaunchedEffect(Store.focusTick) {                               // vừa xem ảnh xong: cuộn tới ảnh đó
        val u = Store.focusUid
        if (u != null) {
            val idx = entries.indexOfFirst { it is Entry.Photo && it.img.uid == u }
            if (idx >= 0) { gstate.scrollToItem((idx - 3).coerceAtLeast(0)); Store.focusUid = null }
        }
    }
    Column(Modifier.fillMaxSize()) {
      androidx.compose.runtime.key(gsig, gfit, gw) {
        LazyVerticalGrid(GridCells.Fixed(gcols), Modifier.fillMaxSize().pinchZoom(gpz).dragSelect(gstate, { u -> uidIndex[u] ?: -1 }) { i -> (entries.getOrNull(i) as? Entry.Photo)?.img?.uid }, state = gstate, contentPadding = PaddingValues(top = topPad), horizontalArrangement = Arrangement.spacedBy(2.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            items(entries.size, key = { i -> when (val e = entries[i]) { is Entry.Header -> e.key; is Entry.Photo -> e.img.uid } },
                span = { i -> val e = entries[i]; if (e is Entry.Header) GridItemSpan(maxLineSpan) else GridItemSpan((e as Entry.Photo).span) }) { i ->
                when (val e = entries[i]) {
                    is Entry.Header -> Text(e.text, Modifier.fillMaxWidth().padding(start = 12.dp, top = 14.dp, bottom = 6.dp), style = MaterialTheme.typography.titleSmall)
                    is Entry.Photo -> {
                        val on = e.img.uid in sel
                        Tile(e.img, on, sel.isNotEmpty(), { Store.selected = if (on) sel - e.img.uid else sel + e.img.uid }, { open(flat, e.pos) }, 1f, e.h)
                    }
                }
            }
        }
      }
    }
}

/** Ảnh có thu phóng đúng vị trí: chụm hai ngón thì điểm giữa hai ngón đứng yên; nhấp đúp phóng tại điểm chạm. */
@Composable
fun ZoomImage(uid: String, onTap: () -> Unit, onZoom: (Boolean) -> Unit) {
    var bmp by remember(uid) { mutableStateOf<Bitmap?>(null) }
    var scale by remember(uid) { mutableStateOf(1f) }
    var offset by remember(uid) { mutableStateOf(Offset.Zero) }
    LaunchedEffect(uid) {
        bmp = Store.thumb(uid)
        bmp = Store.original(uid) ?: bmp
    }
    fun clampOffset(o: Offset, s: Float, size: IntSize): Offset {
        if (s <= 1f) return Offset.Zero
        val mx = (s - 1f) * size.width / 2f
        val my = (s - 1f) * size.height / 2f
        return Offset(o.x.coerceIn(-mx, mx), o.y.coerceIn(-my, my))
    }
    val zoomScope = rememberCoroutineScope()
    var zoomJob by remember(uid) { mutableStateOf<kotlinx.coroutines.Job?>(null) }
    /** Chuyển mượt tới (scale, offset) mới trong 220 ms. */
    fun animateTo(ns: Float, no: Offset) {
        zoomJob?.cancel()
        val s0 = scale
        val o0 = offset
        zoomJob = zoomScope.launch {
            val a = Animatable(0f)
            a.animateTo(1f, tween(220)) {
                scale = s0 + (ns - s0) * value
                offset = Offset(o0.x + (no.x - o0.x) * value, o0.y + (no.y - o0.y) * value)
            }
            scale = ns
            offset = no
        }
    }
    Box(
        Modifier.fillMaxSize()
            .pointerInput(uid) {
                detectTapGestures(onTap = { onTap() }, onDoubleTap = { tap ->
                    // gõ hai lần: phóng to tại đúng điểm gõ, gõ hai lần nữa để thu về vừa khung
                    val center = Offset(size.width / 2f, size.height / 2f)
                    if (scale > 1.01f) {                                   // đang phóng to (bằng gõ đúp hay chụm ngón): gõ đúp để thu về vừa khung toàn màn hình
                        animateTo(1f, Offset.Zero)
                        onZoom(false)
                    } else {
                        val ns = 2.5f
                        animateTo(ns, clampOffset((tap - center) * (1f - ns), ns, size))   // điểm gõ đứng yên khi phóng
                        onZoom(true)
                    }
                })
            }
            .pointerInput(uid) {
                awaitEachGesture {
                    val down0 = awaitFirstDown(requireUnconsumed = false)
                    var panning = false                                     // chưa kéo: một cái chạm nhẹ (kể cả gõ đúp khi đang phóng to) không bị coi là kéo ảnh
                    do {
                        val ev = awaitPointerEvent(PointerEventPass.Main)
                        if (ev.changes.size >= 2) panning = true
                        else if (scale > 1f && (ev.changes.first().position - down0.position).getDistance() > viewConfiguration.touchSlop) panning = true
                        if (panning && (ev.changes.size >= 2 || scale > 1f)) {
                            val zoom = ev.calculateZoom()
                            val c0 = ev.calculateCentroid(useCurrent = false)
                            val c1 = ev.calculateCentroid(useCurrent = true)
                            if (c0 != Offset.Unspecified && c1 != Offset.Unspecified) {
                                val center = Offset(size.width / 2f, size.height / 2f)
                                val old = scale
                                val ns = (old * zoom).coerceIn(1f, 6f)
                                // điểm nội dung dưới trọng tâm hai ngón trước đó phải nằm dưới trọng tâm hiện tại
                                val o = (c1 - center) - (c0 - center - offset) * (ns / old)
                                scale = ns
                                offset = clampOffset(o, ns, size)
                                onZoom(ns > 1f)
                            }
                            ev.changes.forEach { if (it.positionChanged()) it.consume() }
                        }
                    } while (ev.changes.any { it.pressed })
                }
            },
        contentAlignment = Alignment.Center
    ) {
        val b = bmp
        if (b == null) CircularProgressIndicator(color = Color.White)
        else Image(b.asImageBitmap(), null, Modifier.fillMaxSize().graphicsLayer { scaleX = scale; scaleY = scale; translationX = offset.x; translationY = offset.y }, contentScale = ContentScale.Fit)
    }
}
