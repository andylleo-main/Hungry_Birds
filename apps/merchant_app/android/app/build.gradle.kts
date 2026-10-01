import java.io.FileInputStream
import java.util.Properties

plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
    // Must come after com.android.application: it hooks the Android variants to
    // process google-services.json. The build fails outright if that file is
    // missing, which is why this app gained Firebase only once the file existed.
    id("com.google.gms.google-services")
}

// Release signing secrets live in android/key.properties, which is gitignored.
// See README.md ("Building the apps") for how to generate the keystore.
val keystorePropertiesFile = rootProject.file("key.properties")
val hasReleaseKeystore = keystorePropertiesFile.exists()
val keystoreProperties = Properties().apply {
    if (hasReleaseKeystore) {
        FileInputStream(keystorePropertiesFile).use { load(it) }
    }
}

android {
    namespace = "food.hungrybirds.merchant"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        // Reverse domain, matching the product's actual spelling.
        //
        // Two earlier attempts are worth remembering. It was first
        // in.ac.bitmesra.hungerbirds.* - the reverse of the institute's domain -
        // which Gradle rejects outright: "in" is a reserved word and not a valid
        // Java identifier, so the namespace could never be a legal package name.
        // The Kotlin DSL took backticks around it, which is why that survived
        // review while the build failed at assembleRelease every time.
        //
        // Then it was food.hungerbirds.*, carrying the project's old name. That
        // built fine but read as a typo next to everything else calling this
        // Hungry Birds, so it was corrected before anybody outside the team had
        // installed it. Changing it again would not be free: Android identifies
        // an app by this string, so a change means existing installs cannot take
        // an update and have to be uninstalled first.
        applicationId = "food.hungrybirds.merchant"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        // Uses the version code from pubspec.yaml. When using split APKs, 1000 * ABI_VERSION
        // is added automatically by Flutter. (https://developer.android.com/studio/build/configure-apk-splits#configure-APK-versions)
        // You can force using the value of versionCode by specifying the `-P force-version-code-ignoring-abi=true`
        // flag during build.
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    signingConfigs {
        if (hasReleaseKeystore) {
            create("release") {
                keyAlias = keystoreProperties["keyAlias"] as String
                keyPassword = keystoreProperties["keyPassword"] as String
                storeFile = file(keystoreProperties["storeFile"] as String)
                storePassword = keystoreProperties["storePassword"] as String
            }
        }
    }

    buildTypes {
        release {
            // Falls back to debug signing when key.properties is absent (fresh
            // clone) so `flutter run --release` still works. Never distribute a
            // debug-signed APK: the debug key differs per machine, so users
            // would have to uninstall/reinstall to take an update.
            signingConfig = if (hasReleaseKeystore) {
                signingConfigs.getByName("release")
            } else {
                signingConfigs.getByName("debug")
            }
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

flutter {
    source = "../.."
}
