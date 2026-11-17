plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

android {
    namespace = "vn.pp.photos"
    compileSdk = 34
    defaultConfig {
        applicationId = "vn.pp.photos"
        minSdk = 26
        targetSdk = 34
        versionCode = (System.getenv("PP_VERSION_CODE") ?: "1").toInt()
        versionName = System.getenv("PP_VERSION_NAME") ?: "0.1.0"
    }
    signingConfigs {
        create("pp") {
            // khóa ký được mã hóa trong kho (pp.keystore.enc); bản dựng trên GitHub giải mã bằng mật khẩu nằm trong Secrets rồi trỏ tới tệp tạm
            storeFile = file(System.getenv("PP_KEYSTORE_FILE") ?: "pp.keystore")
            storePassword = "privatepicture"
            keyAlias = "pp"
            keyPassword = "privatepicture"
        }
    }
    buildTypes {
        getByName("release") {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("pp")
        }
        getByName("debug") { signingConfig = signingConfigs.getByName("pp") }
    }
    buildFeatures { compose = true }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    packaging { resources.excludes += setOf("/META-INF/{AL2.0,LGPL2.1}", "META-INF/versions/**") }
}

dependencies {
    implementation(platform("androidx.compose:compose-bom:2024.09.00"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.activity:activity-compose:1.9.2")
    implementation("androidx.biometric:biometric:1.1.0")
    implementation("androidx.fragment:fragment-ktx:1.8.3")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.6")
    implementation("com.google.android.gms:play-services-auth:21.2.0")
    implementation("org.bouncycastle:bcprov-jdk18on:1.78.1")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")
}
