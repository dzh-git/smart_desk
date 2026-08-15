plugins {
    id("com.android.application")
}

android {
    namespace = "com.smartdesk.tablet"

    compileSdk {
        version = release(36) {
            minorApiLevel = 1
        }
    }

    defaultConfig {
        applicationId = "com.smartdesk.tablet"
        minSdk = 23
        targetSdk = 36
        versionCode = 10
        versionName = "0.8.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }

    buildFeatures {
        buildConfig = true
    }

    androidResources {
        noCompress += "tflite"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

}

dependencies {
    val cameraXVersion = "1.6.1"

    implementation("androidx.activity:activity:1.13.0")
    implementation("androidx.camera:camera-core:$cameraXVersion")
    implementation("androidx.camera:camera-camera2:$cameraXVersion")
    implementation("androidx.camera:camera-lifecycle:$cameraXVersion")
    implementation("androidx.camera:camera-view:$cameraXVersion")
    implementation("androidx.exifinterface:exifinterface:1.4.2")
    implementation("com.google.mlkit:face-detection:16.1.7")
    implementation("com.google.ai.edge.litert:litert:1.4.2")
    implementation("com.google.code.gson:gson:2.11.0") {
        isTransitive = false
    }

    testImplementation("junit:junit:4.13.2")
}

val workspaceRoot = rootProject.layout.projectDirectory.dir("../..")

val checkModelLicenseGate by tasks.registering(Exec::class) {
    group = "verification"
    description = "Blocks release builds until model commercial rights are approved."
    workingDir(workspaceRoot)
    commandLine(
        "python",
        "scripts/check_model_license_gate.py",
        "--mode",
        "release"
    )
}

tasks.configureEach {
    if (name == "preReleaseBuild") {
        dependsOn(checkModelLicenseGate)
    }
}
