// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

/// @title DidRegistry
/// @notice On-chain Verifiable Data Registry for a tripartite SSI trust model
///         (Issuer / Holder / Verifier). Stores DID -> public key bindings and
///         a revocation ledger for verifiable credentials anchored by hash.
/// @dev    Raw PII is never stored on-chain. Only DIDs, public keys, and
///         opaque keccak256 credential hashes ever touch this contract.
contract DidRegistry {
    struct DidDocument {
        address controller;
        bytes publicKey;
        uint256 created;
        bool exists;
    }

    // did (string) => DID document
    mapping(string => DidDocument) private didDocuments;

    // keccak256(credentialId || commitment) => anchored?
    mapping(bytes32 => bool) private anchoredCredentials;

    // keccak256(credentialId || commitment) => revoked?
    mapping(bytes32 => bool) private revokedCredentials;

    // keccak256(credentialId || commitment) => revocation timestamp
    mapping(bytes32 => uint256) private revocationTimestamp;

    event DidRegistered(string indexed did, address indexed controller, uint256 timestamp);
    event CredentialAnchored(bytes32 indexed credentialHash, string issuerDid, uint256 timestamp);
    event CredentialRevoked(bytes32 indexed credentialHash, address indexed revoker, uint256 timestamp);

    modifier onlyController(string memory did) {
        require(didDocuments[did].exists, "DidRegistry: DID not registered");
        require(didDocuments[did].controller == msg.sender, "DidRegistry: caller is not DID controller");
        _;
    }

    /// @notice Register a new DID with its associated public key material.
    /// @param did The decentralized identifier string (e.g. did:ssi:issuer:xyz).
    /// @param publicKey Raw public key bytes bound to this DID.
    function registerDid(string calldata did, bytes calldata publicKey) external {
        require(!didDocuments[did].exists, "DidRegistry: DID already registered");
        didDocuments[did] = DidDocument({
            controller: msg.sender,
            publicKey: publicKey,
            created: block.timestamp,
            exists: true
        });
        emit DidRegistered(did, msg.sender, block.timestamp);
    }

    /// @notice Fetch the public key bound to a DID.
    function getDidPublicKey(string calldata did) external view returns (bytes memory) {
        require(didDocuments[did].exists, "DidRegistry: DID not registered");
        return didDocuments[did].publicKey;
    }

    /// @notice Fetch the controller (Ethereum address) that manages a DID.
    function getDidController(string calldata did) external view returns (address) {
        require(didDocuments[did].exists, "DidRegistry: DID not registered");
        return didDocuments[did].controller;
    }

    /// @notice Check whether a DID has been registered.
    function didExists(string calldata did) external view returns (bool) {
        return didDocuments[did].exists;
    }

    /// @notice Anchor a credential commitment hash on-chain under an issuer DID.
    /// @param issuerDid The DID of the issuer anchoring the credential.
    /// @param credentialHash keccak256(credentialId || selectiveDisclosureCommitment).
    function anchorCredential(string calldata issuerDid, bytes32 credentialHash) external onlyController(issuerDid) {
        anchoredCredentials[credentialHash] = true;
        emit CredentialAnchored(credentialHash, issuerDid, block.timestamp);
    }

    /// @notice Check whether a credential hash has been anchored.
    function isAnchored(bytes32 credentialHash) external view returns (bool) {
        return anchoredCredentials[credentialHash];
    }

    /// @notice Revoke a previously anchored credential. Only the issuer DID's
    ///         controller may revoke it.
    function revokeCredential(string calldata issuerDid, bytes32 credentialHash) external onlyController(issuerDid) {
        require(!revokedCredentials[credentialHash], "DidRegistry: credential already revoked");
        revokedCredentials[credentialHash] = true;
        revocationTimestamp[credentialHash] = block.timestamp;
        emit CredentialRevoked(credentialHash, msg.sender, block.timestamp);
    }

    /// @notice Check whether a credential hash has been revoked. This is the
    ///         primary call a Verifier (customs) makes at border check time.
    function isRevoked(bytes32 credentialHash) external view returns (bool) {
        return revokedCredentials[credentialHash];
    }

    /// @notice Fetch the block timestamp a credential was revoked at (0 if not revoked).
    function getRevocationTimestamp(bytes32 credentialHash) external view returns (uint256) {
        return revocationTimestamp[credentialHash];
    }
}
