# Untitled string in Configuration of Loki Schema

```txt
http://schema.nethserver.org/loki/get-configuration.json#/properties/active_to
```

The ISO 8601 date-time when the Loki instance was deactivated.

| Abstract            | Extensible | Status         | Identifiable            | Custom Properties | Additional Properties | Access Restrictions | Defined In                                                                     |
| :------------------ | :--------- | :------------- | :---------------------- | :---------------- | :-------------------- | :------------------ | :----------------------------------------------------------------------------- |
| Can be instantiated | No         | Unknown status | Unknown identifiability | Forbidden         | Allowed               | none                | [get-configuration.json\*](loki/get-configuration.json "open original schema") |

## active\_to Type

`string`

## active\_to Constraints

**date time**: the string must be a date time string, according to [RFC 3339, section 5.6](https://tools.ietf.org/html/rfc3339 "check the specification")
