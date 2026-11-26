# Toxicgram Android authentication prototype

Independent test application in the upstream fork. This is NOT the migrated Telegram client: it tests the Toxicgram server login and logout without MTProto. Session is kept only in process memory. No messaging yet. From the repository root, build with a Java 17 and Android SDK 35 environment: `./gradlew -p toxicgram-android :app:assembleDebug`. Debug APK: toxicgram-android/app/build/outputs/apk/debug/app-debug.apk.
