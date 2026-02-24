# Configure Syslog Forwarder Schema

```txt
http://schema.nethserver.org/loki/set-syslog-forwarder.json
```

Configure Syslog Forwarder service.

| Abstract            | Extensible | Status         | Identifiable | Custom Properties | Additional Properties | Access Restrictions | Defined In                                                                         |
| :------------------ | :--------- | :------------- | :----------- | :---------------- | :-------------------- | :------------------ | :--------------------------------------------------------------------------------- |
| Can be instantiated | No         | Unknown status | No           | Forbidden         | Allowed               | none                | [set-syslog-forwarder.json](loki/set-syslog-forwarder.json "open original schema") |

## Configure Syslog Forwarder Type

`object` ([Configure Syslog Forwarder](set-syslog-forwarder.md))

one (and only one) of

* [Untitled undefined type in Configure Syslog Forwarder](set-syslog-forwarder-oneof-0.md "check type definition")

* [Untitled undefined type in Configure Syslog Forwarder](set-syslog-forwarder-oneof-1.md "check type definition")

# Configure Syslog Forwarder Properties

| Property                   | Type      | Required | Nullable       | Defined by                                                                                                                                                       |
| :------------------------- | :-------- | :------- | :------------- | :--------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [active](#active)          | `boolean` | Optional | cannot be null | [Configure Syslog Forwarder](set-syslog-forwarder-properties-active.md "http://schema.nethserver.org/loki/set-syslog-forwarder.json#/properties/active")         |
| [address](#address)        | `string`  | Optional | cannot be null | [Configure Syslog Forwarder](set-syslog-forwarder-properties-address.md "http://schema.nethserver.org/loki/set-syslog-forwarder.json#/properties/address")       |
| [port](#port)              | `string`  | Optional | cannot be null | [Configure Syslog Forwarder](set-syslog-forwarder-properties-port.md "http://schema.nethserver.org/loki/set-syslog-forwarder.json#/properties/port")             |
| [protocol](#protocol)      | `string`  | Optional | cannot be null | [Configure Syslog Forwarder](set-syslog-forwarder-properties-protocol.md "http://schema.nethserver.org/loki/set-syslog-forwarder.json#/properties/protocol")     |
| [format](#format)          | `string`  | Optional | cannot be null | [Configure Syslog Forwarder](set-syslog-forwarder-properties-format.md "http://schema.nethserver.org/loki/set-syslog-forwarder.json#/properties/format")         |
| [start\_time](#start_time) | `string`  | Optional | cannot be null | [Configure Syslog Forwarder](set-syslog-forwarder-properties-start_time.md "http://schema.nethserver.org/loki/set-syslog-forwarder.json#/properties/start_time") |
| [filter](#filter)          | `string`  | Optional | cannot be null | [Configure Syslog Forwarder](set-syslog-forwarder-properties-filter.md "http://schema.nethserver.org/loki/set-syslog-forwarder.json#/properties/filter")         |

## active

Action condition to be set.

`active`

* is optional

* Type: `boolean`

* cannot be null

* defined in: [Configure Syslog Forwarder](set-syslog-forwarder-properties-active.md "http://schema.nethserver.org/loki/set-syslog-forwarder.json#/properties/active")

### active Type

`boolean`

## address

Syslog server address.

`address`

* is optional

* Type: `string`

* cannot be null

* defined in: [Configure Syslog Forwarder](set-syslog-forwarder-properties-address.md "http://schema.nethserver.org/loki/set-syslog-forwarder.json#/properties/address")

### address Type

`string`

## port

Syslog server port.

`port`

* is optional

* Type: `string`

* cannot be null

* defined in: [Configure Syslog Forwarder](set-syslog-forwarder-properties-port.md "http://schema.nethserver.org/loki/set-syslog-forwarder.json#/properties/port")

### port Type

`string`

## protocol

Protocol to send datas.

`protocol`

* is optional

* Type: `string`

* cannot be null

* defined in: [Configure Syslog Forwarder](set-syslog-forwarder-properties-protocol.md "http://schema.nethserver.org/loki/set-syslog-forwarder.json#/properties/protocol")

### protocol Type

`string`

## format

Log format.

`format`

* is optional

* Type: `string`

* cannot be null

* defined in: [Configure Syslog Forwarder](set-syslog-forwarder-properties-format.md "http://schema.nethserver.org/loki/set-syslog-forwarder.json#/properties/format")

### format Type

`string`

## start\_time

Log forwarding start time.

`start_time`

* is optional

* Type: `string`

* cannot be null

* defined in: [Configure Syslog Forwarder](set-syslog-forwarder-properties-start_time.md "http://schema.nethserver.org/loki/set-syslog-forwarder.json#/properties/start_time")

### start\_time Type

`string`

## filter

Log filter type

`filter`

* is optional

* Type: `string`

* cannot be null

* defined in: [Configure Syslog Forwarder](set-syslog-forwarder-properties-filter.md "http://schema.nethserver.org/loki/set-syslog-forwarder.json#/properties/filter")

### filter Type

`string`
