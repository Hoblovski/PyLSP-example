def resolve_positionals(args, data, variables):
    if len(args) == 2:
        x, y = args
    elif len(args) == 1:
        x, y = *args, None
    else:
        x = y = None

    for name, var in zip("yx", (y, x)):
        if var is not None:
            variables = {name: var, **variables}

    return data, variables

