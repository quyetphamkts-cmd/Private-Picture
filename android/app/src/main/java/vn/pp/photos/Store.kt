package vn.pp.photos

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.util.Base64
import android.util.LruCache
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

class Img(val uid: String, val name: String, val taken: String, val w: Int, val h: Int, val orig: Boolean)
class Person(val id: Int, var name: String, val n: Int)
class Label(val id: Int, val name: String)
class Combo(val names: List<String>, val archives: Int, val uids: List<String>, val flag: Boolean = false, val issues: List<String> = emptyList())
class Job(val provider: String, val kind: String, val created: String, val status: String)
class AppUpdate(val version: String, val code: Long, val apkId: String)

/** Toàn bộ dữ liệu thư viện đã giải mã trong bộ nhớ + tải ảnh theo yêu cầu. */
object Store {
    var images by mutableStateOf(listOf<Img>())
    var persons by mutableStateOf(listOf<Person>())
    var labels by mutableStateOf(listOf<Label>())
    var jobs by mutableStateOf(listOf<Job>())
    var personOf = mutableMapOf<String, MutableList<Int>>()
    var labelOf = mutableMapOf<String, MutableSet<Int>>()
    var version by mutableStateOf(0)
    var guesses by mutableStateOf(mapOf<Int, List<Pair<String, Float>>>())      // người -> ảnh app chưa chắc chắn là của người đó (mã ảnh, độ khớp) chờ bạn xác nhận
    private val guessMemo = HashMap<String, Float>()
    var combos by mutableStateOf(listOf<Combo>())                  // tổ hợp người cùng xuất hiện trong một tệp nén (PC tính)
    var clothing by mutableStateOf(mapOf<String, String>())      // uid -> mã loại trang phục (do PC phân tích)
    var covers by mutableStateOf(mapOf<Int, String>())            // mã người -> chữ ký ảnh profile (PC chọn tự động và cắt sẵn, điện thoại chỉ tải về dùng)
    var backP by mutableStateOf(0f)                              // tiến độ vuốt từ cạnh để quay lại (0 = không vuốt), vị trí ngón tay và cạnh trái / phải
    var backY by mutableStateOf(0f)
    var backRight by mutableStateOf(false)
    var selected by mutableStateOf(setOf<String>())              // ảnh đang chọn: dùng chung mọi tab, đổi tab không mất (chỉ vuốt từ cạnh hoặc bấm ✕ mới bỏ)
    var layout by mutableStateOf("day")                          // bố cục lưới ảnh: "fit" (vừa vặn), "day" (ngày), "month" (tháng)
    var showDates by mutableStateOf(true)                        // hiện ngày trong lưới
    private lateinit var viewPrefs: android.content.SharedPreferences
    fun setView(l: String, d: Boolean) {
        layout = l; showDates = d
        viewPrefs.edit().putString("layout", l).putBoolean("dates", d).apply()
    }
    var pool by mutableStateOf(listOf<Img>())                     // danh sách ảnh của màn hình đang xem: "Chọn ảnh tương tự" tìm trong danh sách này
    var focusUid by mutableStateOf<String?>(null)                 // ảnh vừa xem xong: danh sách cuộn tới đó
    var focusTick by mutableStateOf(0)
    fun focus(uid: String) { focusUid = uid; focusTick++ }
    var favPersons by mutableStateOf(setOf<Int>())              // người đã bấm trái tim (lưu ngay trên điện thoại)

    private var key: ByteArray? = null
    private var thumbIds = mapOf<String, String>()
    private var origIds = mapOf<String, String>()
    private var coverIds = mapOf<String, String>()
    private var inboxId: String? = null
    private var rootFolderId: String? = null
    private var indexStamp = ""                                     // thời điểm chỉnh sửa của index.pe trên Drive lần tải gần nhất
    private var appFolderId: String? = null
    private var clipId: String? = null
    private var clipVec: FloatArray? = null
    private var clipIdx: Map<String, Int> = emptyMap()
    private const val DIM = 512
    private lateinit var cache: File
    private val bmp = object : LruCache<String, Bitmap>(((Runtime.getRuntime().maxMemory() / 5).toInt())) {
        override fun sizeOf(k: String, v: Bitmap) = v.byteCount
    }

    private lateinit var prefs: android.content.SharedPreferences
    private var lastPw = ""
    var isOpen by mutableStateOf(false)             // đã mở thư viện (đã qua màn hình đăng nhập)

    /** Kiểm tra lại mật khẩu đồng bộ khi mở khóa lại (dùng khi điện thoại không có vân tay hoặc khóa màn hình). */
    fun checkPassword(pw: String) = lastPw.isNotEmpty() && pw == lastPw

    fun init(ctx: Context) {
        cache = File(ctx.cacheDir, "pp").also { it.mkdirs() }
        prefs = ctx.getSharedPreferences("pp_pending", Context.MODE_PRIVATE)
        favPrefs = ctx.getSharedPreferences("pp_fav", Context.MODE_PRIVATE)
        viewPrefs = ctx.getSharedPreferences("pp_view", Context.MODE_PRIVATE)
        layout = viewPrefs.getString("layout", "day") ?: "day"
        showDates = viewPrefs.getBoolean("dates", true)
        posPrefs = ctx.getSharedPreferences("pp_pos", Context.MODE_PRIVATE)
        modelCols = posPrefs.getInt("cols", 4).coerceIn(3, 5)
        favPersons = favPrefs.getStringSet("persons", emptySet())?.mapNotNull { it.toIntOrNull() }?.toSet() ?: emptySet()
    }

    private lateinit var favPrefs: android.content.SharedPreferences
    private lateinit var posPrefs: android.content.SharedPreferences

    /** Vị trí danh sách người (chữ cái đang mở và vị trí cuộn từng chữ cái): nhớ khi đổi tab và cả khi khởi động lại app. */
    var modelCols by mutableStateOf(4)                              // số người mỗi hàng ở danh sách Model (3, 4 hoặc 5), chụm / giãn hai ngón để đổi; nhớ cho lần mở sau
    fun setModelColumns(n: Int) {
        val v = n.coerceIn(3, 5)
        if (v != modelCols) { modelCols = v; posPrefs.edit().putInt("cols", v).apply() }
    }
    var modelLetter: String
        get() = posPrefs.getString("letter", "") ?: ""
        set(v) { posPrefs.edit().putString("letter", v).apply() }
    fun modelScrollOf(key: String): Pair<Int, Int> = Pair(posPrefs.getInt("i_$key", 0), posPrefs.getInt("o_$key", 0))
    fun setModelScroll(key: String, index: Int, offset: Int) { posPrefs.edit().putInt("i_$key", index).putInt("o_$key", offset).apply() }

    /** Bật / tắt trái tim Favorite của một người. */
    fun toggleFavPerson(id: Int) {
        val on = id !in favPersons
        favPersons = if (on) favPersons + id else favPersons - id                   // đổi trên điện thoại ngay
        favPrefs.edit().putStringSet("persons", favPersons.map { it.toString() }.toSet()).apply()
        bgScope.launch { try { commit(JSONArray().put(op("person_fav").put("person_id", id).put("fav", on))) } catch (e: Exception) { } }          // và gửi cho PC (bên nào bấm sau cùng thì thắng)
    }

    /** Thao tác điện thoại gửi mà PC đã xác nhận nhận / xét xong (danh mục ghi rõ). null nếu danh mục cũ chưa có thông tin này. */
    private var acked: Set<String>? = null

    /** Tải lại dữ liệu từ Drive (sau khi PC đồng bộ), giữ nguyên các thay đổi của điện thoại chưa được PC xử lý. */
    suspend fun reload(onStep: (String) -> Unit = {}) {
        if (lastPw.isNotEmpty()) open(lastPw, onStep)
    }

    /** PC vừa đồng bộ dữ liệu mới lên Drive (index.pe đổi) thì tự tải lại ở nền, không cần bấm ↻. Trả về true nếu đã tải lại. */
    suspend fun refreshIfRemoteChanged(): Boolean {
        val root = rootFolderId ?: return false
        if (lastPw.isEmpty()) return false
        val stamp = try { withContext(Dispatchers.IO) { Drive.list(root).firstOrNull { it.name == "index.pe" }?.modified ?: "" } } catch (e: Exception) { return false }
        if (stamp.isEmpty() || stamp == indexStamp) return false
        reload()
        return true
    }

    fun clearCache() {
        bmp.evictAll()
        cache.listFiles()?.forEach { it.delete() }
    }

    suspend fun open(password: String, onStep: (String) -> Unit) = withContext(Dispatchers.IO) {
        onStep("Đang tìm thư mục đồng bộ trên Drive…")
        val roots = Drive.findFolders("PrivatePicture-Sync")
        if (roots.isEmpty()) throw RuntimeException("Chưa thấy thư mục PrivatePicture-Sync trên Drive. Hãy bấm Đồng bộ trên PC và chờ Drive tải lên.")
        // chọn thư mục đã đủ dữ liệu (có index.pe); nếu có nhiều thư mục trùng tên thì bỏ qua cái còn trống
        var root = roots[0]
        var top: List<DFile> = emptyList()
        for ((i, r) in roots.withIndex()) {
            val t = Drive.list(r)                                   // (mỗi thư mục chỉ liệt kê một lần)
            if (i == 0) top = t
            if (t.any { it.name == "index.pe" }) { root = r; top = t; break }
        }
        fun idOf(n: String) = top.firstOrNull { it.name == n }?.id
        val meta = JSONObject(Drive.download(idOf("sync.json") ?: throw RuntimeException("Thiếu sync.json trong thư mục đồng bộ trên Drive.")).toString(Charsets.UTF_8))
        onStep("Đang kiểm tra mật khẩu…")
        val k = Crypto.derive(password, Base64.decode(meta.getString("salt"), Base64.DEFAULT))
        Crypto.unseal(k, Base64.decode(meta.getString("check"), Base64.DEFAULT))
        key = k
        onStep("Đang tải danh mục…")
        val idx = JSONObject(Crypto.unseal(k, Drive.download(idOf("index.pe") ?: throw RuntimeException("Chưa có index.pe: máy tính chưa đồng bộ xong, hoặc Google Drive trên máy tính chưa tải lên xong. Chờ biểu tượng Drive ngừng quay rồi thử lại."))).toString(Charsets.UTF_8))
        parse(idx)
        applyPendingLocal()                                        // áp dụng ngay các thao tác của điện thoại chưa được PC nhận (không chờ mạng): mở lại app không thấy ảnh đã xác nhận "quay về chưa xác nhận"
        loadIdCache()                                              // danh sách tệp ảnh nhỏ / ảnh gốc của lần trước: dùng ngay, làm mới ở nền
        inboxId = idOf("inbox")
        rootFolderId = root
        indexStamp = top.firstOrNull { it.name == "index.pe" }?.modified ?: ""
        appFolderId = idOf("app")
        clipId = idOf("clip.pe")
        clipVec = null            // tải lại vectơ khi PC có bản mới
        lastPw = password
        isOpen = true
        // phần nặng (liệt kê hàng chục nghìn tệp trên Drive, đẩy thay đổi đang chờ) chạy ở nền để giao diện hiện ra ngay
        val tf = idOf("thumbs"); val of = idOf("orig"); val cf = idOf("covers")
        idsJob = bgScope.async {
            coroutineScope {
                val a = async { tf?.let { f -> Drive.list(f).associate { it.name.removeSuffix(".pe") to it.id } } }
                val b = async { of?.let { f -> Drive.list(f).associate { it.name.removeSuffix(".pe") to it.id } } }
                val c = async { cf?.let { f -> Drive.list(f).associate { it.name.removeSuffix(".pe") to it.id } } }
                c.await()?.let { coverIds = it }
                a.await()?.let { thumbIds = it }
                b.await()?.let { origIds = it }
            }
            saveIdCache()
        }
        bgScope.async { try { syncPending() } catch (e: Exception) { } }
        startPreload()
    }

    private val preloadSem = Semaphore(2)
    @Volatile var viewerActive = false                           // đang xem ảnh: việc tải ngầm của danh sách tạm nhường hết đường mạng cho ảnh đang xem

    /** Danh sách chỉ tải ảnh nhỏ (preview) và chỉ tải khi cần; lúc mở app chỉ tải sẵn vừa một màn hình đầu (48 ảnh mới nhất), việc này dừng ngay khi bắt đầu xem ảnh. */
    private fun startPreload() {
        bgScope.launch {
            try { idsJob?.await() } catch (e: Exception) { }
            val recent = images.sortedByDescending { it.taken }.take(48)
            coroutineScope {
                for (im in recent) launch {
                    preloadSem.withPermit {
                        while (viewerActive) kotlinx.coroutines.delay(500)
                        try { thumb(im.uid) } catch (e: Exception) { }
                    }
                }
            }
        }
    }

    /** Ảnh gốc đã có sẵn trong bộ nhớ chưa (để việc tải trước không giành đường mạng với ảnh đang xem). */
    fun originalReady(uid: String): Boolean = bmp.get("o$uid") != null

    private val bgScope = kotlinx.coroutines.CoroutineScope(kotlinx.coroutines.SupervisorJob() + Dispatchers.IO)
    private var idsJob: kotlinx.coroutines.Deferred<Unit>? = null

    private fun loadIdCache() {
        fun read(name: String): Map<String, String> = try {
            val f = File(cache, name)
            if (!f.exists()) emptyMap() else f.readLines().mapNotNull { l -> l.split('\t').let { if (it.size == 2) it[0] to it[1] else null } }.toMap()
        } catch (e: Exception) { emptyMap() }
        val t = read("ids-t.tsv"); val o = read("ids-o.tsv")
        if (t.isNotEmpty()) thumbIds = t
        if (o.isNotEmpty()) origIds = o
    }

    private fun saveIdCache() {
        try {
            File(cache, "ids-t.tsv").writeText(thumbIds.entries.joinToString("\n") { it.key + "\t" + it.value })
            File(cache, "ids-o.tsv").writeText(origIds.entries.joinToString("\n") { it.key + "\t" + it.value })
        } catch (e: Exception) { }
    }

    private fun parse(j: JSONObject) {
        val im = j.getJSONArray("images")
        val l = ArrayList<Img>()
        for (i in 0 until im.length()) {
            val o = im.getJSONObject(i)
            l.add(Img(o.getString("uid"), o.optString("name"), o.optString("taken", "").let { if (it == "null") "" else it },
                o.optInt("w"), o.optInt("h"), o.optBoolean("orig")))
        }
        l.sortByDescending { it.taken }
        images = l
        val ps = j.getJSONArray("persons")
        persons = (0 until ps.length()).map { ps.getJSONObject(it).let { o -> Person(o.getInt("id"), o.optString("name").let { n -> if (n == "null") "" else n }, o.optInt("n")) } }
        val favFromIndex = (0 until ps.length()).map { ps.getJSONObject(it) }.filter { it.optInt("fav") == 1 }.map { it.getInt("id") }.toSet()
        if (ps.length() > 0 && ps.getJSONObject(0).has("fav")) {                      // trái tim người cũng đồng bộ hai chiều: danh mục là nguồn chính
            if (!favPrefs.getBoolean("migrated", false)) {                              // lần đầu: trái tim đã bấm riêng trên điện thoại trước đây được gửi cho PC
                val legacy = favPrefs.getStringSet("persons", emptySet())?.mapNotNull { it.toIntOrNull() }?.toSet() ?: emptySet()
                favPrefs.edit().putBoolean("migrated", true).apply()
                val extra = legacy - favFromIndex
                if (extra.isNotEmpty()) { val ops = JSONArray(); for (id in extra) ops.put(op("person_fav").put("person_id", id).put("fav", true)); enqueue(ops).let { pp -> bgScope.launch { try { if (upload(pp)) markSent(pp.name) } catch (e: Exception) { } } } }
                favPersons = favFromIndex + extra
            } else favPersons = favFromIndex
            favPrefs.edit().putStringSet("persons", favPersons.map { it.toString() }.toSet()).apply()
        }
        val ak = j.optJSONArray("acked")
        acked = if (ak == null) null else (0 until ak.length()).map { ak.getString(it) }.toSet()
        val ls = j.getJSONArray("labels")
        labels = (0 until ls.length()).map { ls.getJSONObject(it).let { o -> Label(o.getInt("id"), o.getString("name")) } }
        val ip = j.getJSONArray("image_person")
        personOf = mutableMapOf()
        for (i in 0 until ip.length()) {
            val a = ip.getJSONArray(i)
            personOf.getOrPut(a.getString(0)) { mutableListOf() }.add(a.getInt(1))
        }
        val li = j.getJSONArray("label_images")
        labelOf = mutableMapOf()
        for (i in 0 until li.length()) {
            val a = li.getJSONArray(i)
            labelOf.getOrPut(a.getString(0)) { mutableSetOf() }.add(a.getInt(1))
        }
        val cl = j.optJSONArray("clothing")
        val cm = HashMap<String, String>()
        if (cl != null) for (i in 0 until cl.length()) { val a = cl.getJSONArray(i); cm[a.getString(0)] = a.getString(1) }
        clothing = cm
        val cv = j.optJSONObject("covers")
        val cvm = HashMap<Int, String>()
        if (cv != null) for (k in cv.keys()) cvm[k.toInt()] = cv.getString(k)
        covers = cvm
        val gs = j.optJSONArray("guesses")
        val gm = HashMap<Int, MutableList<Pair<String, Float>>>()
        if (gs != null) for (i in 0 until gs.length()) { val a = gs.getJSONArray(i); gm.getOrPut(a.getInt(1)) { mutableListOf() }.add(a.getString(0) to a.getDouble(2).toFloat()) }
        guesses = gm
        val cb = j.optJSONArray("combos")
        val cl2 = ArrayList<Combo>()
        if (cb != null) for (i in 0 until cb.length()) {
            val o = cb.getJSONObject(i)
            val ns = o.getJSONArray("names"); val us = o.getJSONArray("uids")
            val iss = o.optJSONArray("issues")
            cl2.add(Combo((0 until ns.length()).map { ns.getString(it) }, o.optInt("archives"), (0 until us.length()).map { us.getString(it) },
                o.optBoolean("flag"), if (iss == null) emptyList() else (0 until iss.length()).map { iss.getString(it) }))
        }
        combos = cl2
        version++
    }

    /** Giữ tối đa 16 ảnh gốc đã tải gần nhất trên đĩa (nạp trước khi xem); xóa các ảnh cũ hơn. */
    private fun trimOrigCache(keep: Int = 16) {
        val files = cache.listFiles { f -> f.name.startsWith("o-") }?.sortedByDescending { it.lastModified() } ?: return
        for (f in files.drop(keep)) f.delete()
    }

    private suspend fun fetchEnc(kind: String, uid: String): ByteArray? {
        val f = File(cache, "$kind-$uid.pe")
        if (f.exists()) return f.readBytes()
        var id = (if (kind == "t") thumbIds else origIds)[uid]
        if (id == null) { try { idsJob?.await() } catch (e: Exception) { }; id = (if (kind == "t") thumbIds else origIds)[uid] }     // chưa có trong danh sách đệm: chờ danh sách mới từ Drive
        if (id == null) return null
        val b = Drive.download(id)
        f.writeBytes(b)                    // lưu đệm (vẫn ở dạng mã hóa): ảnh nhỏ giữ lâu; ảnh gốc chỉ giữ vài ảnh gần nhất để xem liền mạch
        if (kind == "o") trimOrigCache()
        return b
    }

    /** Giải mã ảnh gốc từ Drive: đúng từng byte như tệp trên máy tính (AES-GCM kiểm tra toàn vẹn nên hỏng một byte là báo lỗi). */
    suspend fun originalBytes(uid: String): ByteArray = withContext(Dispatchers.IO) {
        val e = fetchEnc("o", uid) ?: throw RuntimeException("Chưa có ảnh gốc trên Drive (PC cần bật Đồng bộ cả ảnh gốc).")
        Crypto.unseal(key ?: throw RuntimeException("Chưa mở khóa"), e)
    }

    /** Lưu ảnh gốc nguyên bản vào thư viện ảnh của điện thoại (Pictures/PrivatePicture). Trả về đường dẫn đã lưu. */
    suspend fun saveOriginal(ctx: Context, im: Img): String {
        if (android.os.Build.VERSION.SDK_INT < 29) throw RuntimeException("Cần Android 10 trở lên để lưu ảnh vào thư viện.")
        val data = originalBytes(im.uid)
        return withContext(Dispatchers.IO) {
            val name = im.name.ifBlank { im.uid + ".jpg" }
            val ext = name.substringAfterLast('.', "jpg").lowercase()
            val mime = android.webkit.MimeTypeMap.getSingleton().getMimeTypeFromExtension(ext) ?: "image/jpeg"
            val values = android.content.ContentValues().apply {
                put(android.provider.MediaStore.Images.Media.DISPLAY_NAME, name)
                put(android.provider.MediaStore.Images.Media.MIME_TYPE, mime)
                put(android.provider.MediaStore.Images.Media.RELATIVE_PATH, "Pictures/PrivatePicture")
                put(android.provider.MediaStore.Images.Media.IS_PENDING, 1)
            }
            val uri = ctx.contentResolver.insert(android.provider.MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values)
                ?: throw RuntimeException("Không tạo được tệp trong thư viện ảnh")
            ctx.contentResolver.openOutputStream(uri)!!.use { it.write(data) }
            values.clear()
            values.put(android.provider.MediaStore.Images.Media.IS_PENDING, 0)
            ctx.contentResolver.update(uri, values, null, null)
            "Pictures/PrivatePicture/$name"
        }
    }

    /** Ảnh profile của một người: PC đã chọn và cắt sẵn (nét, từ ảnh gốc); điện thoại chỉ tải về, lưu đệm và hiển thị. */
    suspend fun cover(pid: Int): Bitmap? = withContext(Dispatchers.IO) {
        val sig = covers[pid] ?: return@withContext null
        val name = "$pid-$sig"
        bmp.get("c$name")?.let { return@withContext it }
        try {
            val f = File(cache, "c-$name.pe")
            val e = if (f.exists()) f.readBytes() else {
                var id = coverIds[name]
                if (id == null) { try { idsJob?.await() } catch (x: Exception) { }; id = coverIds[name] }
                if (id == null) return@withContext null
                Drive.download(id).also { f.writeBytes(it) }
            }
            val d = Crypto.unseal(key!!, e)
            val b = BitmapFactory.decodeByteArray(d, 0, d.size)
            if (b != null) bmp.put("c$name", b)
            b
        } catch (x: Exception) { null }
    }

    suspend fun thumb(uid: String): Bitmap? = withContext(Dispatchers.IO) {
        bmp.get("t$uid")?.let { return@withContext it }
        try {
            val e = fetchEnc("t", uid) ?: return@withContext null
            val d = Crypto.unseal(key!!, e)
            val b = BitmapFactory.decodeByteArray(d, 0, d.size)
            if (b != null) bmp.put("t$uid", b)
            b
        } catch (e: Exception) { null }
    }

    suspend fun original(uid: String, maxSide: Int = 2048): Bitmap? = withContext(Dispatchers.IO) {
        bmp.get("o$uid")?.let { return@withContext it }
        try {
            val e = fetchEnc("o", uid) ?: return@withContext thumb(uid)
            val d = Crypto.unseal(key!!, e)
            val o = BitmapFactory.Options().apply { inJustDecodeBounds = true }
            BitmapFactory.decodeByteArray(d, 0, d.size, o)
            var s = 1
            while (o.outWidth / s > maxSide || o.outHeight / s > maxSide) s *= 2
            val b = BitmapFactory.decodeByteArray(d, 0, d.size, BitmapFactory.Options().apply { inSampleSize = s }) ?: return@withContext thumb(uid)
            bmp.put("o$uid", b)
            b
        } catch (e: Exception) { thumb(uid) }
    }

    // ------------------------------------------------------------ tự cập nhật app qua Drive (PC đặt APK mới vào thư mục app/)
    suspend fun checkUpdate(installedCode: Long): AppUpdate? = withContext(Dispatchers.IO) {
        try {
            val f = appFolderId ?: return@withContext null
            val files = Drive.list(f)
            val vj = files.firstOrNull { it.name == "version.json" } ?: return@withContext null
            val apk = files.firstOrNull { it.name.endsWith(".apk") } ?: return@withContext null
            val j = JSONObject(Drive.download(vj.id).toString(Charsets.UTF_8))
            val code = j.optLong("code")
            if (code > installedCode) AppUpdate(j.optString("version"), code, apk.id) else null
        } catch (e: Exception) { null }
    }

    suspend fun downloadApk(u: AppUpdate): File = withContext(Dispatchers.IO) {
        val f = File(cache, "update.apk")
        f.writeBytes(Drive.download(u.apkId))
        f
    }

    // ------------------------------------------------------------ chọn ảnh tương tự / gợi ý nhãn (vectơ nội dung do PC đồng bộ)
    private fun half(h: Int): Float {
        val s = (h shr 15) and 1
        val e = (h shr 10) and 0x1f
        val m = h and 0x3ff
        val f = when (e) {
            0 -> if (m == 0) 0f else (m / 1024f) * Math.pow(2.0, -14.0).toFloat()
            31 -> 0f
            else -> (1f + m / 1024f) * Math.pow(2.0, (e - 15).toDouble()).toFloat()
        }
        return if (s == 1) -f else f
    }

    /** Tải vectơ nội dung ảnh từ Drive (lần đầu dùng). Trả về false nếu PC chưa đồng bộ vectơ. */
    suspend fun ensureClip(): Boolean = withContext(Dispatchers.IO) {
        if (clipVec != null) return@withContext true
        val id = clipId ?: return@withContext false
        try {
            val body = Crypto.unseal(key ?: return@withContext false, Drive.download(id))
            if (body.size < 12 || String(body, 0, 4, Charsets.US_ASCII) != "PPV1") return@withContext false
            val bb = java.nio.ByteBuffer.wrap(body).order(java.nio.ByteOrder.LITTLE_ENDIAN)
            val n = bb.getInt(4)
            val dim = bb.getInt(8)
            if (dim != DIM) return@withContext false
            val idx = HashMap<String, Int>(n * 2)
            for (i in 0 until n) idx[String(body, 12 + 20 * i, 20, Charsets.US_ASCII).trimEnd('\u0000')] = i
            val vec = FloatArray(n * dim)
            var p = 12 + 20 * n
            for (k in 0 until n * dim) {
                vec[k] = half((body[p].toInt() and 0xff) or ((body[p + 1].toInt() and 0xff) shl 8))
                p += 2
            }
            clipIdx = idx
            clipVec = vec
            true
        } catch (e: Exception) { false }
    }

    private fun dotWith(proto: FloatArray, row: Int): Float {
        val v = clipVec ?: return 0f
        var s = 0f
        val o = row * DIM
        for (d in 0 until DIM) s += proto[d] * v[o + d]
        return s
    }

    private fun prototype(uids: Collection<String>): FloatArray? {
        val v = clipVec ?: return null
        val rows = uids.mapNotNull { clipIdx[it] }
        if (rows.isEmpty()) return null
        val p = FloatArray(DIM)
        for (r in rows) for (d in 0 until DIM) p[d] += v[r * DIM + d]
        var n = 0f
        for (d in 0 until DIM) n += p[d] * p[d]
        n = Math.sqrt(n.toDouble()).toFloat().coerceAtLeast(1e-6f)
        for (d in 0 until DIM) p[d] /= n
        return p
    }

    /** Trong `pool`, các ảnh giống các ảnh đã chọn từ mức `thr` trở lên (độ giống cosine). */
    fun similar(selected: Collection<String>, pool: List<Img>, thr: Float): List<String> {
        val proto = prototype(selected) ?: return emptyList()
        return pool.filter { im -> clipIdx[im.uid]?.let { dotWith(proto, it) >= thr } == true }.map { it.uid }
    }

    /** Gợi ý cho một nhãn: ảnh chưa có nhãn nào, xếp theo độ giống với các ảnh của nhãn (từ cao đến thấp). */
    fun suggestFor(label: Label, minSim: Float = 0.78f, limit: Int = 300): List<Pair<Img, Float>> {
        val members = images.filter { labelOf[it.uid]?.contains(label.id) == true }.map { it.uid }
        val proto = prototype(members) ?: return emptyList()
        return images.filter { (labelOf[it.uid] ?: emptySet<Int>()).isEmpty() }
            .mapNotNull { im -> clipIdx[im.uid]?.let { r -> val s = dotWith(proto, r); if (s >= minSim) im to s else null } }
            .sortedByDescending { it.second }.take(limit)
    }

    // ------------------------------------------------------------ chỉnh sửa hai chiều (bên nào sửa sau cùng thì thắng)
    // Mỗi thao tác được áp dụng ngay trên điện thoại, kèm dấu thời gian, rồi gửi về PC qua thư mục inbox. PC chỉ chấp nhận nếu mới hơn
    // lần sửa gần nhất của đúng mục đó trên PC. Thay đổi chưa được PC xử lý được giữ lại và phủ lên dữ liệu mỗi lần tải lại.
    private class Pending(val name: String, val ops: String, var sent: Boolean)

    private fun loadPending(): MutableList<Pending> {
        val arr = try { JSONArray(prefs.getString("list", "[]")) } catch (e: Exception) { JSONArray() }
        return (0 until arr.length()).map { arr.getJSONObject(it).let { o -> Pending(o.getString("name"), o.getString("ops"), o.optBoolean("sent")) } }.toMutableList()
    }

    private fun savePending(list: List<Pending>) {
        val arr = JSONArray()
        for (p in list) arr.put(JSONObject().put("name", p.name).put("ops", p.ops).put("sent", p.sent))
        prefs.edit().putString("list", arr.toString()).commit()          // ghi đồng bộ xuống bộ nhớ: tắt app ngay sau khi bấm cũng không mất thao tác (apply() có thể chưa kịp ghi)
    }

    private suspend fun upload(p: Pending): Boolean {
        val k = key ?: return false
        val inbox = inboxId ?: return false
        return try {
            val body = JSONObject().put("device", "android").put("ops", JSONArray(p.ops)).toString().toByteArray(Charsets.UTF_8)
            Drive.upload(inbox, p.name, Crypto.seal(k, body))
            true
        } catch (e: Exception) { false }
    }

    private suspend fun syncPending() {
        val inbox = inboxId
        val snapshot = synchronized(pendLock) { loadPending() }
        for (p in snapshot) if (!p.sent && upload(p)) markSent(p.name)
        val present = if (inbox != null) try { Drive.list(inbox).map { it.name }.toSet() } catch (e: Exception) { null } else null
        val list = synchronized(pendLock) {
            var l = loadPending()
            // thao tác PC đã nhận (đã biến khỏi inbox) vẫn được giữ thêm 15 phút và áp dụng lên dữ liệu vừa tải: tránh nhìn thấy ảnh đã xác nhận "quay lại chưa xác nhận" khi tải về danh mục cũ hơn lúc PC xử lý xong
            val ak = acked
            val week = 7 * 24 * 3600 * 1000L
            if (ak != null) l = l.filter { it.name !in ak && System.currentTimeMillis() - createdAt(it.name) < week }.toMutableList()      // bỏ thao tác khi PC đã xác nhận nhận (danh mục ghi rõ) hoặc quá 7 ngày: không còn đoán theo thời gian
            else if (present != null) l = l.filter { !it.sent || it.name in present || System.currentTimeMillis() - createdAt(it.name) < 15 * 60 * 1000 }.toMutableList()
            savePending(l)
            l
        }
        for (p in list) applyOps(JSONArray(p.ops))
        version++
    }

    private val pendLock = Any()                                   // mọi thao tác đọc / ghi hàng đợi chờ gửi đều qua khóa này (nhiều thao tác nhanh liên tiếp không ghi đè nhau)

    /** Áp dụng lại các thao tác còn chờ lên dữ liệu vừa tải (chỉ đọc bộ nhớ điện thoại, không dùng mạng). Thao tác PC đã xác nhận nhận thì bỏ qua. */
    private fun applyPendingLocal() {
        val ak = acked
        val list = synchronized(pendLock) { loadPending() }
        for (p in list) if (ak == null || p.name !in ak) try { applyOps(JSONArray(p.ops)) } catch (e: Exception) { }
        version++
    }

    private fun enqueue(ops: JSONArray): Pending = synchronized(pendLock) {
        val p = Pending("android-${System.currentTimeMillis()}-${(1000..9999).random()}.pe", ops.toString(), false)
        val list = loadPending()
        list.add(p)
        savePending(list)
        p
    }

    private fun markSent(name: String) = synchronized(pendLock) {
        val list = loadPending()
        list.firstOrNull { it.name == name }?.sent = true
        savePending(list)
    }

    /** Tên tệp 'android-<mili giây>-<số>.pe': thời điểm tạo, dùng để giữ lại thao tác vừa được PC nhận trong một lúc. */
    private fun createdAt(name: String): Long = name.split("-").getOrNull(1)?.toLongOrNull() ?: 0L

    private var labelSeq = -1

    private fun labelByName(name: String): Label {
        labels.firstOrNull { it.name == name }?.let { return it }
        val l = Label(labelSeq--, name)
        labels = labels + l
        return l
    }

    private fun recountPersons() {
        persons = persons.map { p -> Person(p.id, p.name, personOf.values.count { it.contains(p.id) }) }
    }

    /** Áp dụng các thao tác lên dữ liệu trong bộ nhớ (dùng cho cả thao tác mới và các thay đổi chưa được PC xử lý). */
    private fun applyOps(ops: JSONArray) {
        for (i in 0 until ops.length()) {
            val o = ops.getJSONObject(i)
            when (o.getString("op")) {
                "rename_person" -> persons.firstOrNull { it.id == o.getInt("person_id") }?.name = o.optString("name")
                "label_add" -> {
                    val l = labelByName(o.getString("name"))
                    labelOf.getOrPut(o.getString("image_uid")) { mutableSetOf() }.add(l.id)
                }
                "label_remove" -> labels.firstOrNull { it.name == o.getString("name") }?.let { l -> labelOf[o.getString("image_uid")]?.remove(l.id) }
                "label_rename" -> {
                    val l = labels.firstOrNull { it.name == o.getString("name") }
                    val nn = o.getString("new_name").trim()
                    if (l != null && nn.isNotEmpty() && nn != l.name) {
                        val other = labels.firstOrNull { it.name == nn && it.id != l.id }
                        if (other != null) {
                            for (set in labelOf.values) if (set.remove(l.id)) set.add(other.id)
                            labels = labels.filter { it.id != l.id }
                        } else labels = labels.map { if (it.id == l.id) Label(l.id, nn) else it }
                    }
                }
                "label_delete" -> labels.firstOrNull { it.name == o.getString("name") }?.let { l ->
                    for (set in labelOf.values) set.remove(l.id)
                    labels = labels.filter { it.id != l.id }
                }
                "person_merge" -> {
                    val a = o.getInt("src_id"); val b = o.getInt("dst_id")
                    for (l in personOf.values) if (l.remove(a) && !l.contains(b)) l.add(b)
                    persons = persons.filter { it.id != a }
                    recountPersons()
                }
                "cloth_set" -> clothing = clothing + (o.getString("image_uid") to o.getString("grp"))
                "cloth_clear" -> clothing = clothing - o.getString("image_uid")
                "person_hide" -> persons = persons.filter { it.id != o.getInt("person_id") }
                "person_remove" -> {
                    personOf[o.getString("image_uid")]?.remove(o.getInt("person_id"))
                    recountPersons()
                }
                "guess_accept", "guess_reject" -> {                       // xác nhận đúng / không phải người này: ảnh hết là đề xuất
                    val pid = o.getInt("person_id"); val u = o.getString("image_uid")
                    guesses[pid]?.firstOrNull { it.first == u }?.let { guessMemo["$u|$pid"] = it.second }
                    guesses = guesses + (pid to (guesses[pid] ?: emptyList()).filter { it.first != u })
                    if (o.getString("op") == "guess_accept") {
                        val l = personOf.getOrPut(u) { mutableListOf() }
                        if (!l.contains(pid)) l.add(pid)
                        recountPersons()
                    }
                }
                "person_fav" -> {                                          // trái tim người (đồng bộ hai chiều)
                    val pid = o.getInt("person_id")
                    favPersons = if (o.optBoolean("fav")) favPersons + pid else favPersons - pid
                }
                "guess_restore" -> {                                      // hoàn tác: ảnh về lại danh sách đề xuất
                    val pid = o.getInt("person_id"); val u = o.getString("image_uid")
                    personOf[u]?.remove(pid)
                    if ((guesses[pid] ?: emptyList()).none { it.first == u }) guesses = guesses + (pid to ((guesses[pid] ?: emptyList()) + (u to (guessMemo["$u|$pid"] ?: 0.5f))))
                    recountPersons()
                }
                "person_restore", "person_add" -> {                       // hoàn tác loại nhầm / thêm ảnh vào một người
                    val pid = o.getInt("person_id")
                    val l = personOf.getOrPut(o.getString("image_uid")) { mutableListOf() }
                    if (!l.contains(pid)) l.add(pid)
                    recountPersons()
                }
                "person_create" -> {                                       // tạo người mới từ các ảnh đã chọn (mã tạm trên điện thoại, PC cấp mã thật khi đồng bộ)
                    val tid = o.optInt("temp_id", -1)
                    if (persons.none { it.id == tid }) persons = persons + Person(tid, o.getString("name"), 0)
                    val us = o.getJSONArray("image_uids")
                    for (i in 0 until us.length()) {
                        val l = personOf.getOrPut(us.getString(i)) { mutableListOf() }
                        if (!l.contains(tid)) l.add(tid)
                    }
                    recountPersons()
                }
            }
        }
    }

    private suspend fun commit(ops: JSONArray) {
        applyOps(ops)                                              // áp dụng trên điện thoại NGAY: giao diện đổi tức thì
        version++
        val p = enqueue(ops)                                       // ghi vào hàng đợi trên điện thoại NGAY (không mất nếu tắt app hoặc mất mạng ngay sau đó)
        bgScope.launch { try { if (upload(p)) markSent(p.name) } catch (e: Exception) { } }          // gửi lên Drive ở nền, không bắt người dùng chờ mạng
    }

    private fun op(kind: String) = JSONObject().put("op", kind).put("ts", System.currentTimeMillis() / 1000.0)

    /** Phân loại Dressed / Naked cho ảnh: ghi trên điện thoại ngay, PC áp dụng như phân loại tay khi đồng bộ. */
    suspend fun setCloth(uids: Collection<String>, grp: String) {
        val ops = JSONArray()
        for (u in uids) ops.put(op("cloth_set").put("image_uid", u).put("grp", grp))
        commit(ops)
    }

    fun labelsOn(uids: Collection<String>): List<Pair<Label, Int>> =
        labels.map { l -> l to uids.count { labelOf[it]?.contains(l.id) == true } }.filter { it.second > 0 }

    fun isFav(uid: String): Boolean {
        val f = labels.firstOrNull { it.name == "Yêu thích" } ?: return false
        return labelOf[uid]?.contains(f.id) == true
    }

    suspend fun toggleFav(uid: String) {
        val on = !isFav(uid)
        commit(JSONArray().put(op(if (on) "label_add" else "label_remove").put("image_uid", uid).put("name", "Yêu thích")))
    }

    suspend fun rename(p: Person, name: String) =
        commit(JSONArray().put(op("rename_person").put("person_id", p.id).put("name", name)))

    suspend fun labelAdd(uids: Collection<String>, name: String) {
        val ops = JSONArray()
        for (u in uids) ops.put(op("label_add").put("image_uid", u).put("name", name.trim()))
        commit(ops)
    }

    suspend fun labelRemove(uids: Collection<String>, name: String) {
        val ops = JSONArray()
        for (u in uids) ops.put(op("label_remove").put("image_uid", u).put("name", name))
        commit(ops)
    }

    suspend fun labelChange(uids: Collection<String>, old: String, new: String) {
        val ops = JSONArray()
        for (u in uids) ops.put(op("label_remove").put("image_uid", u).put("name", old))
        for (u in uids) ops.put(op("label_add").put("image_uid", u).put("name", new.trim()))
        commit(ops)
    }

    suspend fun labelRename(l: Label, newName: String) {
        val nn = newName.trim()
        if (nn.isEmpty() || nn == l.name) return
        commit(JSONArray().put(op("label_rename").put("name", l.name).put("new_name", nn)))
    }

    suspend fun labelDelete(l: Label) = commit(JSONArray().put(op("label_delete").put("name", l.name)))

    suspend fun personMerge(src: Person, dst: Person) =
        commit(JSONArray().put(op("person_merge").put("src_id", src.id).put("dst_id", dst.id)))

    suspend fun personHide(p: Person) = commit(JSONArray().put(op("person_hide").put("person_id", p.id)))

    suspend fun personRestore(p: Person, uids: Collection<String>) {
        val ops = JSONArray()
        for (u in uids) ops.put(op("person_restore").put("person_id", p.id).put("image_uid", u))
        commit(ops)
    }

    suspend fun personAdd(p: Person, uids: Collection<String>) {
        val ops = JSONArray()
        for (u in uids) ops.put(op("person_add").put("person_id", p.id).put("image_uid", u))
        commit(ops)
    }

    /** Ảnh app chưa chắc chắn là của người này (chưa thuộc người này), độ khớp cao trước. */
    fun suggestionsOf(pid: Int): List<Pair<String, Float>> = (guesses[pid] ?: emptyList()).filter { personOf[it.first]?.contains(pid) != true }.sortedByDescending { it.second }

    suspend fun guessAccept(p: Person, uids: Collection<String>) { val ops = JSONArray(); for (u in uids) ops.put(op("guess_accept").put("person_id", p.id).put("image_uid", u)); commit(ops) }
    suspend fun guessReject(p: Person, uids: Collection<String>) { val ops = JSONArray(); for (u in uids) ops.put(op("guess_reject").put("person_id", p.id).put("image_uid", u)); commit(ops) }
    suspend fun guessRestore(p: Person, uids: Collection<String>) { val ops = JSONArray(); for (u in uids) ops.put(op("guess_restore").put("person_id", p.id).put("image_uid", u)); commit(ops) }

    suspend fun personCreate(name: String, uids: Collection<String>): Person {
        val tid = -(1 + (System.currentTimeMillis() % 1_000_000_000L).toInt())
        commit(JSONArray().put(op("person_create").put("name", name.trim()).put("temp_id", tid).put("image_uids", JSONArray(uids.toList()))))
        return persons.first { it.id == tid }
    }

    /** Bỏ phân loại tay của ảnh (dùng khi hoàn tác một phân loại mà ảnh trước đó chưa có loại). */
    suspend fun clearCloth(uids: Collection<String>) {
        val ops = JSONArray()
        for (u in uids) ops.put(op("cloth_clear").put("image_uid", u))
        commit(ops)
    }

    suspend fun personRemove(p: Person, uids: Collection<String>) {
        val ops = JSONArray()
        for (u in uids) ops.put(op("person_remove").put("person_id", p.id).put("image_uid", u))
        commit(ops)
    }
}
