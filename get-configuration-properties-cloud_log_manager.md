# Untitled object in Configuration of Loki Schema

```txt
http://schema.nethserver.org/loki/get-configuration.json#/properties/cloud_log_manager
```

Cloud Log Manager forwarder configuration.

| Abstract            | Extensible | Status         | Identifiable | Custom Properties | Additional Properties | Access Restrictions | Defined In                                                                     |
| :------------------ | :--------- | :------------- | :----------- | :---------------- | :-------------------- | :------------------ | :----------------------------------------------------------------------------- |
| Can be instantiated | No         | Unknown status | No           | Forbidden         | Allowed               | none                | [get-configuration.json\*](loki/get-configuration.json "open original schema") |

## cloud\_log\_manager Type

`object` ([Details](get-configuration-properties-cloud_log_manager.md))

# cloud\_log\_manager Properties

| Property                           | Type     | Required | Nullable       | Defined by                                                                                                                                                                                                              |
| :--------------------------------- | :------- | :------- | :------------- | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [status](#status)                  | `string` | Required | cannot be null | [Configuration of Loki](get-configuration-properties-cloud_log_manager-properties-status.md "http://schema.nethserver.org/loki/get-configuration.json#/properties/cloud_log_manager/properties/status")                 |
| [address](#address)                | `string` | Optional | cannot be null | [Configuration of Loki](get-configuration-properties-cloud_log_manager-properties-address.md "http://schema.nethserver.org/loki/get-configuration.json#/properties/cloud_log_manager/properties/address")               |
| [tenant](#tenant)                  | `string` | Optional | cannot be null | [Configuration of Loki](get-configuration-properties-cloud_log_manager-properties-tenant.md "http://schema.nethserver.org/loki/get-configuration.json#/properties/cloud_log_manager/properties/tenant")                 |
| [last\_timestamp](#last_timestamp) | `string` | Optional | cannot be null | [Configuration of Loki](get-configuration-properties-cloud_log_manager-properties-last_timestamp.md "http://schema.nethserver.org/loki/get-configuration.json#/properties/cloud_log_manager/properties/last_timestamp") |
| [cluster\_id](#cluster_id)         | `string` | Optional | cannot be null | [Configuration of Loki](get-configuration-properties-cloud_log_manager-properties-cluster_id.md "http://schema.nethserver.org/loki/get-configuration.json#/properties/cloud_log_manager/properties/cluster_id")         |

## status

Forwarder state.

`status`

* is required

* Type: `string`

* cannot be null

* defined in: [Configuration of Loki](get-configuration-properties-cloud_log_manager-properties-status.md "http://schema.nethserver.org/loki/get-configuration.json#/properties/cloud_log_manager/properties/status")

### status Type

`string`

## address

Forwarder address where datas are sent.

`address`

* is optional

* Type: `string`

* cannot be null

* defined in: [Configuration of Loki](get-configuration-properties-cloud_log_manager-properties-address.md "http://schema.nethserver.org/loki/get-configuration.json#/properties/cloud_log_manager/properties/address")

### address Type

`string`

## tenant

Cloud Log Manager internal data.

`tenant`

* is optional

* Type: `string`

* cannot be null

* defined in: [Configuration of Loki](get-configuration-properties-cloud_log_manager-properties-tenant.md "http://schema.nethserver.org/loki/get-configuration.json#/properties/cloud_log_manager/properties/tenant")

### tenant Type

`string`

## last\_timestamp

Timestamp of the last log sent.

`last_timestamp`

* is optional

* Type: `string`

* cannot be null

* defined in: [Configuration of Loki](get-configuration-properties-cloud_log_manager-properties-last_timestamp.md "http://schema.nethserver.org/loki/get-configuration.json#/properties/cloud_log_manager/properties/last_timestamp")

### last\_timestamp Type

`string`

## cluster\_id

Key that identify cluster on Cloud Log Manager.

`cluster_id`

* is optional

* Type: `string`

* cannot be null

* defined in: [Configuration of Loki](get-configuration-properties-cloud_log_manager-properties-cluster_id.md "http://schema.nethserver.org/loki/get-configuration.json#/properties/cloud_log_manager/properties/cluster_id")

### cluster\_id Type

`string`
