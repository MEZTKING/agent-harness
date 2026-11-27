pluginManagement {
    repositories {
        google()
        // On CI, Google's copy of Maven Central first: repo.maven.apache.org refuses runners with 429s.
        if (System.getenv("CI") != null) maven("https://maven-central.storage-download.googleapis.com/maven2/")
        mavenCentral()
        gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        // On CI, Google's copy of Maven Central first: repo.maven.apache.org refuses runners with 429s.
        if (System.getenv("CI") != null) maven("https://maven-central.storage-download.googleapis.com/maven2/")
        mavenCentral()
    }
}
rootProject.name = "RoundtableMobile"
include(":app")
