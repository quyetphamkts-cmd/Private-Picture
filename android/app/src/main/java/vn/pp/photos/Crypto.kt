package vn.pp.photos

import org.bouncycastle.crypto.generators.SCrypt
import java.security.SecureRandom
import javax.crypto.Cipher
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

/** Khớp với src/pp/secure.py và docs/SYNC_FORMAT.md của bản PC. */
object Crypto {
    private val MAGIC = byteArrayOf('P'.code.toByte(), 'P'.code.toByte(), 'E'.code.toByte(), '1'.code.toByte())

    fun derive(password: String, salt: ByteArray): ByteArray =
        SCrypt.generate(password.toByteArray(Charsets.UTF_8), salt, 32768, 8, 1, 32)

    class WrongPassword : Exception("Mật khẩu đồng bộ không đúng")

    fun unseal(key: ByteArray, blob: ByteArray): ByteArray {
        if (blob.size < 32 || !blob.copyOfRange(0, 4).contentEquals(MAGIC)) throw IllegalArgumentException("Tệp không đúng định dạng")
        val c = Cipher.getInstance("AES/GCM/NoPadding")
        c.init(Cipher.DECRYPT_MODE, SecretKeySpec(key, "AES"), GCMParameterSpec(128, blob, 4, 12))
        try {
            return c.doFinal(blob, 16, blob.size - 16)
        } catch (e: Exception) {
            throw WrongPassword()
        }
    }

    fun seal(key: ByteArray, data: ByteArray): ByteArray {
        val nonce = ByteArray(12).also { SecureRandom().nextBytes(it) }
        val c = Cipher.getInstance("AES/GCM/NoPadding")
        c.init(Cipher.ENCRYPT_MODE, SecretKeySpec(key, "AES"), GCMParameterSpec(128, nonce))
        return MAGIC + nonce + c.doFinal(data)
    }
}
