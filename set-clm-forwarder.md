# Configure Cloud Log Manager Forwarder Schema

```txt
http://schema.nethserver.org/loki/set-clm-forwarder.json
```

Configure Cloud Log Manager Forwarder service.

| Abstract            | Extensible | Status         | Identifiable | Custom Properties | Additional Properties | Access Restrictions | Defined In                                                                   |
| :------------------ | :--------- | :------------- | :----------- | :---------------- | :-------------------- | :------------------ | :--------------------------------------------------------------------------- |
| Can be instantiated | No         | Unknown status | No           | Forbidden         | Allowed               | none                | [set-clm-forwarder.json](loki/set-clm-forwarder.json "open original schema") |

## Configure Cloud Log Manager Forwarder Type

`object` ([Configure Cloud Log Manager Forwarder](set-clm-forwarder.md))

one (and only one) of

* [Untitled undefined type in Configure Cloud Log Manager Forwarder](set-clm-forwarder-oneof-0.md "check type definition")

* [Untitled undefined type in Configure Cloud Log Manager Forwarder](set-clm-forwarder-oneof-1.md "check type definition")

# Configure Cloud Log Manager Forwarder Properties

| Property                   | Type      | Required | Nullable       | Defined by                                                                                                                                                            |
| :------------------------- | :-------- | :------- | :------------- | :-------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [active](#active)          | `boolean` | Optional | cannot be null | [Configure Cloud Log Manager Forwarder](set-clm-forwarder-properties-active.md "http://schema.nethserver.org/loki/set-clm-forwarder.json#/properties/active")         |
| [address](#address)        | `string`  | Optional | cannot be null | [Configure Cloud Log Manager Forwarder](set-clm-forwarder-properties-address.md "http://schema.nethserver.org/loki/set-clm-forwarder.json#/properties/address")       |
| [tenant](#tenant)          | `string`  | Optional | cannot be null | [Configure Cloud Log Manager Forwarder](set-clm-forwarder-properties-tenant.md "http://schema.nethserver.org/loki/set-clm-forwarder.json#/properties/tenant")         |
| [start\_time](#start_time) | `string`  | Optional | cannot be null | [Configure Cloud Log Manager Forwarder](set-clm-forwarder-properties-start_time.md "http://schema.nethserver.org/loki/set-clm-forwarder.json#/properties/start_time") |
| [filter](#filter)          | `string`  | Optional | cannot be null | [Configure Cloud Log Manager Forwarder](set-clm-forwarder-properties-filter.md "http://schema.nethserver.org/loki/set-clm-forwarder.json#/properties/filter")         |

## active

Action condition to be set.

`active`

* is optional

* Type: `boolean`

* cannot be null

* defined in: [Configure Cloud Log Manager Forwarder](set-clm-forwarder-properties-active.md "http://schema.nethserver.org/loki/set-clm-forwarder.json#/properties/active")

### active Type

`boolean`

## address

Cloud log manager server address.

`address`

* is optional

* Type: `string`

* cannot be null

* defined in: [Configure Cloud Log Manager Forwarder](set-clm-forwarder-properties-address.md "http://schema.nethserver.org/loki/set-clm-forwarder.json#/properties/address")

### address Type

`string`

## tenant

Cloud log manager tenant.

`tenant`

* is optional

* Type: `string`

* cannot be null

* defined in: [Configure Cloud Log Manager Forwarder](set-clm-forwarder-properties-tenant.md "http://schema.nethserver.org/loki/set-clm-forwarder.json#/properties/tenant")

### tenant Type

`string`

## start\_time

Log forwarding start time.

`start_time`

* is optional

* Type: `string`

* cannot be null

* defined in: [Configure Cloud Log Manager Forwarder](set-clm-forwarder-properties-start_time.md "http://schema.nethserver.org/loki/set-clm-forwarder.json#/properties/start_time")

### start\_time Type

`string`

## filter

Log filter type

`filter`

* is optional

* Type: `string`

* cannot be null

* defined in: [Configure Cloud Log Manager Forwarder](set-clm-forwarder-properties-filter.md "http://schema.nethserver.org/loki/set-clm-forwarder.json#/properties/filter")

### filter Type

`string`
