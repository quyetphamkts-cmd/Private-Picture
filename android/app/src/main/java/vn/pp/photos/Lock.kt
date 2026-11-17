package vn.pp.photos

import android.os.Build
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import androidx.annotation.RequiresApi
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricPrompt
import androidx.core.content.ContextCompat
import androidx.fragment.app.FragmentActivity
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** Mở app bằng vân tay hoặc khóa màn hình (PIN, hình vẽ, mật khẩu) của chính điện thoại.
 *  Mật khẩu đồng bộ được mã hóa bằng một khóa nằm trong Android Keystore, chỉ dùng được sau khi xác thực. */
object Lock {
    private const val ALIAS = "pp_unlock_key"
    private const val WINDOW_SECONDS = 30
    private const val AUTH = BiometricManager.Authenticators.BIOMETRIC_STRONG or BiometricManager.Authenticators.DEVICE_CREDENTIAL

    fun available(act: FragmentActivity): Boolean =
        Build.VERSION.SDK_INT >= Build.VERSION_CODES.R &&
            BiometricManager.from(act).canAuthenticate(AUTH) == BiometricManager.BIOMETRIC_SUCCESS

    fun authenticate(act: FragmentActivity, title: String, onOk: () -> Unit, onFail: (String) -> Unit) {
        val info = BiometricPrompt.PromptInfo.Builder()
            .setTitle(title)
            .setSubtitle("Dùng vân tay hoặc khóa màn hình của điện thoại")
            .setAllowedAuthenticators(AUTH)
            .build()
        val prompt = BiometricPrompt(act, ContextCompat.getMainExecutor(act), object : BiometricPrompt.AuthenticationCallback() {
            override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) = onOk()
            override fun onAuthenticationError(errorCode: Int, errString: CharSequence) = onFail(errString.toString())
        })
        prompt.authenticate(info)
    }

    @RequiresApi(Build.VERSION_CODES.R)
    private fun newKey(): SecretKey {
        val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        if (ks.containsAlias(ALIAS)) ks.deleteEntry(ALIAS)
        val spec = KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setKeySize(256)
            .setUserAuthenticationRequired(true)
            .setUserAuthenticationParameters(WINDOW_SECONDS, KeyProperties.AUTH_BIOMETRIC_STRONG or KeyProperties.AUTH_DEVICE_CREDENTIAL)
            .setInvalidatedByBiometricEnrollment(false)
            .build()
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply { init(spec) }.generateKey()
    }

    private fun existingKey(): SecretKey {
        val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        return ks.getKey(ALIAS, null) as? SecretKey ?: throw IllegalStateException("Chưa có khóa mở nhanh")
    }

    /** Gọi ngay sau khi xác thực thành công. Trả về chuỗi lưu được (iv:dữ liệu, base64). */
    fun encrypt(password: String): String {
        val key = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) newKey() else throw IllegalStateException("Cần Android 11 trở lên")
        val c = Cipher.getInstance("AES/GCM/NoPadding")
        c.init(Cipher.ENCRYPT_MODE, key)
        val ct = c.doFinal(password.toByteArray(Charsets.UTF_8))
        return Base64.encodeToString(c.iv, Base64.NO_WRAP) + ":" + Base64.encodeToString(ct, Base64.NO_WRAP)
    }

    /** Gọi ngay sau khi xác thực thành công (trong 30 giây). */
    fun decrypt(stored: String): String {
        val (iv, ct) = stored.split(":", limit = 2)
        val c = Cipher.getInstance("AES/GCM/NoPadding")
        c.init(Cipher.DECRYPT_MODE, existingKey(), GCMParameterSpec(128, Base64.decode(iv, Base64.NO_WRAP)))
        return String(c.doFinal(Base64.decode(ct, Base64.NO_WRAP)), Charsets.UTF_8)
    }
}
