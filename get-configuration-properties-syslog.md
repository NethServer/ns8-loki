# Untitled object in Configuration of Loki Schema

```txt
http://schema.nethserver.org/loki/get-configuration.json#/properties/syslog
```

Syslog forwarder configuration.

| Abstract            | Extensible | Status         | Identifiable | Custom Properties | Additional Properties | Access Restrictions | Defined In                                                                     |
| :------------------ | :--------- | :------------- | :----------- | :---------------- | :-------------------- | :------------------ | :----------------------------------------------------------------------------- |
| Can be instantiated | No         | Unknown status | No           | Forbidden         | Allowed               | none                | [get-configuration.json\*](loki/get-configuration.json "open original schema") |

## syslog Type

`object` ([Details](get-configuration-properties-syslog.md))

# syslog Properties

| Property                           | Type     | Required | Nullable       | Defined by                                                                                                                                                                                        |
| :--------------------------------- | :------- | :------- | :------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| [status](#status)                  | `string` | Required | cannot be null | [Configuration of Loki](get-configuration-properties-syslog-properties-status.md "http://schema.nethserver.org/loki/get-configuration.json#/properties/syslog/properties/status")                 |
| [address](#address)                | `string` | Optional | cannot be null | [Configuration of Loki](get-configuration-properties-syslog-properties-address.md "http://schema.nethserver.org/loki/get-configuration.json#/properties/syslog/properties/address")               |
| [port](#port)                      | `string` | Optional | cannot be null | [Configuration of Loki](get-configuration-properties-syslog-properties-port.md "http://schema.nethserver.org/loki/get-configuration.json#/properties/syslog/properties/port")                     |
| [protocol](#protocol)              | `string` | Optional | cannot be null | [Configuration of Loki](get-configuration-properties-syslog-properties-protocol.md "http://schema.nethserver.org/loki/get-configuration.json#/properties/syslog/properties/protocol")             |
| [format](#format)                  | `string` | Optional | cannot be null | [Configuration of Loki](get-configuration-properties-syslog-properties-format.md "http://schema.nethserver.org/loki/get-configuration.json#/properties/syslog/properties/format")                 |
| [last\_timestamp](#last_timestamp) | `string` | Optional | cannot be null | [Configuration of Loki](get-configuration-properties-syslog-properties-last_timestamp.md "http://schema.nethserver.org/loki/get-configuration.json#/properties/syslog/properties/last_timestamp") |

## status

Forwarder state.

`status`

* is required

* Type: `string`

* cannot be null

* defined in: [Configuration of Loki](get-configuration-properties-syslog-properties-status.md "http://schema.nethserver.org/loki/get-configuration.json#/properties/syslog/properties/status")

### status Type

`string`

## address

Forwarder address where data are sent.

`address`

* is optional

* Type: `string`

* cannot be null

* defined in: [Configuration of Loki](get-configuration-properties-syslog-properties-address.md "http://schema.nethserver.org/loki/get-configuration.json#/properties/syslog/properties/address")

### address Type

`string`

## port

External server port.

`port`

* is optional

* Type: `string`

* cannot be null

* defined in: [Configuration of Loki](get-configuration-properties-syslog-properties-port.md "http://schema.nethserver.org/loki/get-configuration.json#/properties/syslog/properties/port")

### port Type

`string`

## protocol

Protocol used to send datas.

`protocol`

* is optional

* Type: `string`

* cannot be null

* defined in: [Configuration of Loki](get-configuration-properties-syslog-properties-protocol.md "http://schema.nethserver.org/loki/get-configuration.json#/properties/syslog/properties/protocol")

### protocol Type

`string`

## format

Log format.

`format`

* is optional

* Type: `string`

* cannot be null

* defined in: [Configuration of Loki](get-configuration-properties-syslog-properties-format.md "http://schema.nethserver.org/loki/get-configuration.json#/properties/syslog/properties/format")

### format Type

`string`

## last\_timestamp

Timestamp of the last log sent.

`last_timestamp`

* is optional

* Type: `string`

* cannot be null

* defined in: [Configuration of Loki](get-configuration-properties-syslog-properties-last_timestamp.md "http://schema.nethserver.org/loki/get-configuration.json#/properties/syslog/properties/last_timestamp")

### last\_timestamp Type

`string`
