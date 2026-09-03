# Untitled string in Configuration of Loki Schema

```txt
http://schema.nethserver.org/loki/get-configuration.json#/properties/insights/properties/status
```

State of insights-collector.service.

| Abstract            | Extensible | Status         | Identifiable            | Custom Properties | Additional Properties | Access Restrictions | Defined In                                                                     |
| :------------------ | :--------- | :------------- | :---------------------- | :---------------- | :-------------------- | :------------------ | :----------------------------------------------------------------------------- |
| Can be instantiated | No         | Unknown status | Unknown identifiability | Forbidden         | Allowed               | none                | [get-configuration.json\*](loki/get-configuration.json "open original schema") |

## status Type

`string`

## status Constraints

**enum**: the value of this property must be equal to one of the following values:

| Value        | Explanation |
| :----------- | :---------- |
| `"active"`   |             |
| `"failed"`   |             |
| `"inactive"` |             |
