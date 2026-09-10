# Untitled string in Configure the insights collector Schema

```txt
http://schema.nethserver.org/loki/set-insights.json#/properties/base_url
```

Root URL of the nethesis-insights server, with no path — the collector appends /logs/v1/bundles itself.

| Abstract            | Extensible | Status         | Identifiable            | Custom Properties | Additional Properties | Access Restrictions | Defined In                                                           |
| :------------------ | :--------- | :------------- | :---------------------- | :---------------- | :-------------------- | :------------------ | :------------------------------------------------------------------- |
| Can be instantiated | No         | Unknown status | Unknown identifiability | Forbidden         | Allowed               | none                | [set-insights.json\*](loki/set-insights.json "open original schema") |

## base\_url Type

`string`

## base\_url Constraints

**URI**: the string must be a URI, according to [RFC 3986](https://tools.ietf.org/html/rfc3986 "check the specification")
