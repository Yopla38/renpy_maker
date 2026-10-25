plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

android {
    namespace = "fr.yopla.histoire"
    compileSdk = 35

    defaultConfig {
        applicationId = "fr.yopla.histoire"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"
        // Chaquopy : 64 bits seulement (téléphones récents et émulateur)
        ndk { abiFilters += listOf("arm64-v8a", "x86_64") }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

chaquopy {
    defaultConfig {
        version = "3.12"
        pip {
            install("pyyaml")
        }
    }
}

// Le moteur n'est pas copié à la main : il vient du dépôt renpy_maker (racine, un niveau au-dessus), à chaque compilation.
val engineDir = rootProject.file("..")
val syncEngine by tasks.registering(Sync::class) {
    // Le paquet renpy_maker (code et pages web) garde son dossier ; config.yaml est à côté de launcher.py.
    from(File(engineDir, "src/renpy_maker")) {
        include("**/*.py", "**/*.html")
        into("renpy_maker")
    }
    from(engineDir) {
        include("config.yaml")
    }
    from(rootProject.file("bridge")) {
        include("launcher.py")
    }
    into(layout.projectDirectory.dir("src/main/python"))
}

tasks.named("preBuild") {
    dependsOn(syncEngine)
}

// Chaquopy lit ce dossier : la copie doit avoir lieu avant la fusion des sources Python.
afterEvaluate {
    tasks.matching { it.name.matches(Regex("merge.*PythonSources")) }.configureEach {
        dependsOn(syncEngine)
    }
}
