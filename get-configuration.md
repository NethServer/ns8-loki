# Configuration of Loki Schema

```txt
http://schema.nethserver.org/loki/get-configuration.json
```

Retrieve the configuration of loki instance.

| Abstract            | Extensible | Status         | Identifiable | Custom Properties | Additional Properties | Access Restrictions | Defined In                                                                   |
| :------------------ | :--------- | :------------- | :----------- | :---------------- | :-------------------- | :------------------ | :--------------------------------------------------------------------------- |
| Can be instantiated | No         | Unknown status | No           | Forbidden         | Allowed               | none                | [get-configuration.json](loki/get-configuration.json "open original schema") |

## Configuration of Loki Type

`object` ([Configuration of Loki](get-configuration.md))

# Configuration of Loki Properties

| Property                           | Type      | Required | Nullable       | Defined by                                                                                                                                                    |
| :--------------------------------- | :-------- | :------- | :------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| [retention\_days](#retention_days) | `integer` | Required | cannot be null | [Configuration of Loki](get-configuration-properties-retention_days.md "http://schema.nethserver.org/loki/get-configuration.json#/properties/retention_days") |
| [active\_from](#active_from)       | `string`  | Required | cannot be null | [Configuration of Loki](get-configuration-properties-active_from.md "http://schema.nethserver.org/loki/get-configuration.json#/properties/active_from")       |
| [active\_to](#active_to)           | `string`  | Optional | cannot be null | [Configuration of Loki](get-configuration-properties-active_to.md "http://schema.nethserver.org/loki/get-configuration.json#/properties/active_to")           |

## retention\_days

Retention period of logs, in days.

`retention_days`

*   is required

*   Type: `integer`

*   cannot be null

*   defined in: [Configuration of Loki](get-configuration-properties-retention_days.md "http://schema.nethserver.org/loki/get-configuration.json#/properties/retention_days")

### retention\_days Type

`integer`

### retention\_days Constraints

**minimum**: the value of this number must greater than or equal to: `1`

## active\_from

The ISO 8601 date-time when the Loki instance was activated.

`active_from`

*   is required

*   Type: `string`

*   cannot be null

*   defined in: [Configuration of Loki](get-configuration-properties-active_from.md "http://schema.nethserver.org/loki/get-configuration.json#/properties/active_from")

### active\_from Type

`string`

### active\_from Constraints

**date time**: the string must be a date time string, according to [RFC 3339, section 5.6](https://tools.ietf.org/html/rfc3339 "check the specification")

## active\_to

The ISO 8601 date-time when the Loki instance was deactivated.

`active_to`

*   is optional

*   Type: `string`

*   cannot be null

*   defined in: [Configuration of Loki](get-configuration-properties-active_to.md "http://schema.nethserver.org/loki/get-configuration.json#/properties/active_to")

### active\_to Type

`string`

### active\_to Constraints

**date time**: the string must be a date time string, according to [RFC 3339, section 5.6](https://tools.ietf.org/html/rfc3339 "check the specification")
