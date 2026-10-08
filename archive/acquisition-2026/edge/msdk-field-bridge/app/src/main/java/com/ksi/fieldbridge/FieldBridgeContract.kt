package com.ksi.fieldbridge

/** Pre/postflight-only operations. No flight or camera-write operation can be represented. */
enum class FieldBridgeOperation {
    SIGNED_CONTRACT_TRANSFER,
    MEDIA_READ_ONE,
}

data class FieldBridgeEnvelope(
    val operation: FieldBridgeOperation,
    val organizationId: String,
    val siteId: String,
    val missionId: String,
    val gatewayDeviceId: String,
    val edgeDeviceId: String,
    val artifactSha256: String,
    val idempotencyKey: String,
)

data class FieldBridgeReceipt(
    val providerOperationId: String,
    val acceptedAtUtc: String,
    val itemCount: Int,
    val manifestRef: String?,
)

object FieldBridgePolicy {
    private val identifier = Regex("^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    private val sha256 = Regex("^[0-9a-f]{64}$")

    fun validate(envelope: FieldBridgeEnvelope) {
        val identifiers = listOf(
            envelope.organizationId,
            envelope.siteId,
            envelope.missionId,
            envelope.gatewayDeviceId,
            envelope.edgeDeviceId,
            envelope.idempotencyKey,
        )
        require(identifiers.all(identifier::matches)) { "invalid scoped identifier" }
        require(envelope.gatewayDeviceId != envelope.edgeDeviceId) {
            "gateway and edge device identities must differ"
        }
        require(sha256.matches(envelope.artifactSha256)) { "invalid artifact SHA-256" }
    }
}

interface FieldBridgeTransport {
    suspend fun exchange(envelope: FieldBridgeEnvelope): FieldBridgeReceipt
}
