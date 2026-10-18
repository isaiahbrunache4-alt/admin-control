# BouncyCastle carries code for desktop JVM features Android does not have.
-dontwarn javax.naming.**
-dontwarn org.bouncycastle.**
-keep class org.bouncycastle.crypto.signers.Ed25519Signer { *; }
