package com.koraiq.app

import com.google.android.play.core.integrity.IntegrityManagerFactory
import com.google.android.play.core.integrity.StandardIntegrityManager.PrepareIntegrityTokenRequest
import com.google.android.play.core.integrity.StandardIntegrityManager.StandardIntegrityTokenProvider
import com.google.android.play.core.integrity.StandardIntegrityManager.StandardIntegrityTokenRequest
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

/**
 * Play Integrity *Standard* API bridge for lib/core/integrity.dart.
 *  - "prepare": warms up a token provider once (a few hundred ms, done at app start).
 *  - "token":   returns a token bound to requestHash = sha256("$action:$uid:$nonce").
 * Gradle: implementation("com.google.android.play:integrity:1.4.0")
 */
class MainActivity : FlutterActivity() {
    private var provider: StandardIntegrityTokenProvider? = null

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "koraiq/integrity").setMethodCallHandler { call, result ->
            when (call.method) {
                "prepare" -> {
                    val project = (call.argument<Number>("cloudProjectNumber") ?: 0).toLong()
                    IntegrityManagerFactory.createStandard(applicationContext)
                        .prepareIntegrityToken(
                            PrepareIntegrityTokenRequest.builder().setCloudProjectNumber(project).build()
                        )
                        .addOnSuccessListener { p -> provider = p; result.success(true) }
                        .addOnFailureListener { e -> result.error("PREPARE_FAILED", e.message, null) }
                }
                "token" -> {
                    val p = provider
                    val hash = call.argument<String>("requestHash")
                    if (p == null || hash == null) {
                        result.error("NOT_PREPARED", "Call prepare first", null)
                    } else {
                        p.request(StandardIntegrityTokenRequest.builder().setRequestHash(hash).build())
                            .addOnSuccessListener { r -> result.success(r.token()) }
                            .addOnFailureListener { e ->
                                provider = null // e.g. INTEGRITY_TOKEN_PROVIDER_INVALID -> re-prepare next call
                                result.error("TOKEN_FAILED", e.message, null)
                            }
                    }
                }
                else -> result.notImplemented()
            }
        }
    }
}
