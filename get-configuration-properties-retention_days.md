# Untitled integer in Configuration of Loki Schema

```txt
http://schema.nethserver.org/loki/get-configuration.json#/properties/retention_days
```

Retention period of logs, in days.

| Abstract            | Extensible | Status         | Identifiable            | Custom Properties | Additional Properties | Access Restrictions | Defined In                                                                     |
| :------------------ | :--------- | :------------- | :---------------------- | :---------------- | :-------------------- | :------------------ | :----------------------------------------------------------------------------- |
| Can be instantiated | No         | Unknown status | Unknown identifiability | Forbidden         | Allowed               | none                | [get-configuration.json\*](loki/get-configuration.json "open original schema") |

## retention\_days Type

`integer`

## retention\_days Constraints

**minimum**: the value of this number must greater than or equal to: `1`
