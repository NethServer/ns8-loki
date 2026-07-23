# Configure Loki Schema

```txt
http://schema.nethserver.org/loki/configure-module.json
```

Configure Loki instance.

| Abstract            | Extensible | Status         | Identifiable | Custom Properties | Additional Properties | Access Restrictions | Defined In                                                                 |
| :------------------ | :--------- | :------------- | :----------- | :---------------- | :-------------------- | :------------------ | :------------------------------------------------------------------------- |
| Can be instantiated | No         | Unknown status | No           | Forbidden         | Allowed               | none                | [configure-module.json](loki/configure-module.json "open original schema") |

## Configure Loki Type

`object` ([Configure Loki](configure-module.md))

# Configure Loki Properties

| Property                           | Type      | Required | Nullable       | Defined by                                                                                                                                           |
| :--------------------------------- | :-------- | :------- | :------------- | :--------------------------------------------------------------------------------------------------------------------------------------------------- |
| [retention\_days](#retention_days) | `integer` | Required | cannot be null | [Configure Loki](configure-module-properties-retention_days.md "http://schema.nethserver.org/loki/configure-module.json#/properties/retention_days") |

## retention\_days

Retention period of logs, in days.

`retention_days`

* is required

* Type: `integer`

* cannot be null

* defined in: [Configure Loki](configure-module-properties-retention_days.md "http://schema.nethserver.org/loki/configure-module.json#/properties/retention_days")

### retention\_days Type

`integer`

### retention\_days Constraints

**minimum**: the value of this number must greater than or equal to: `1`
