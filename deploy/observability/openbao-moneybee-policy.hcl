path "kv/data/moneybee/*" {
  capabilities = ["read"]
}

path "kv/metadata/moneybee/*" {
  capabilities = ["read", "list"]
}

path "transit/encrypt/moneybee-field-encryption" {
  capabilities = ["update"]
}

path "transit/decrypt/moneybee-field-encryption" {
  capabilities = ["update"]
}

path "transit/rewrap/moneybee-field-encryption" {
  capabilities = ["update"]
}

path "transit/keys/moneybee-field-encryption" {
  capabilities = ["read"]
}
