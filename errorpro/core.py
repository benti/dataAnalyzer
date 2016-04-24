import numpy as np
from sympy import S, Expr, latex, Function, Symbol

from errorpro.units import parse_unit
from errorpro.quantities import Quantity, get_value, get_error, get_dimension,\
                                convert_to_unit, qtable, adjust_to_unit
from errorpro.dimensions.dimensions import Dimension
from errorpro.dimensions.solvers import dim_solve
from errorpro import plotting_matplotlib as matplot, plotting_gnuplot as gnuplot,\
                     fitting, pytex

from IPython.display import Latex as render_latex

def assign(value, error=None, unit=None, name=None, longname=None, value_unit=None, error_unit=None, ignore_dim=False):
    """ function to create a new quantity

    Args:
     value: number or string that can be parsed by numpy, or sympy
            expression. If it's a sympy expression containing quantities, it
            will perform the calculation, otherwise it just saves the value.
     error: number that is saved as the value's uncertainty. this will replace
            any error coming from a calculation.
     unit: sympy expression of Unit objects. This is used to convert and save
           value and error in base units. Replaces value_unit and error_unit if
           specified.
     name: short name of the quantity (usually one letter). If not specified,
           quantity will get a dummy name.
     longname: optional additional description of the quantity
     value_unit: unit of value. Use this if value and error have different units.
     error_unit: unit of error.
     ignore_dim: bool. Keeps function from raising an error even if calculated
                 and given unit don't match. Then given unit is used instead.
    """

    value_formula = None
    value_factor = 1
    value_dim = Dimension()

    error_formula = None
    error_factor = 1
    error_dim = Dimension()

    # parse units
    if unit is not None:
        # if one general unit is given
        value_factor, value_dim, value_unit = parse_unit(unit)
        error_factor = value_factor
        error_dim = value_dim
        error_unit = value_unit
    else:
        # if value unit is given
        if value_unit is not None:
            value_factor, value_dim, value_unit = parse_unit(value_unit)

        # if error unit is given
        if error_unit is not None:
            error_factor, error_dim, error_unit = parse_unit(error_unit)

            # check dimension consistency between value_dim and error_dim
            if value_unit is not None and not value_dim == error_dim:
                raise RuntimeError("dimension mismatch\n%s != %s" % (value_dim, error_dim))

    # process value

    # if it's a calculation
    if isinstance(value, Expr) and not value.is_number:
        value_formula = value
        value = get_value(value_formula)

        if ignore_dim:
            # with ignore_dim=True, calculated value is converted to given unit
            value = np.float_(value_factor)*np.float_(value)
        else:
            # calculate dimension from dependency
            calculated_dim = get_dimension(value_formula)
            if value_unit is None:
                value_dim = calculated_dim
            else:
                if not calculated_dim == value_dim:
                    raise RuntimeError("dimension mismatch \n%s != %s" % (value_dim, calculated_dim))

    # if it's a number
    else:
        value=np.float_(value_factor)*np.float_(value)

    # process error
    if error is not None:
        error=np.float_(error_factor)*np.float_(error)

        # check value and error shapes and duplicate error in case
        if error.shape == () or value.shape[-len(error.shape):] == error.shape:
            error = np.resize(error, value.shape)
        else:
            raise RuntimeError("length of value and error don't match and "\
                                "can't be adjusted by duplicating.\n"\
                                "%s and %s" % (value.shape, error.shape))

    # if error can be calculated
    elif value_formula is not None:
        error, error_formula = get_error(value_formula)

        if ignore_dim:
            # with ignore_dim=True, calculated error is converted to given unit
            error = np.float_(error_factor)*np.float_(error)


    q = Quantity(name, longname)
    q.value = value
    q.value_formula = value_formula
    q.error = error
    q.error_formula = error_formula
    if value_unit is not None:
        q.prefer_unit = value_unit
    else:
        q.prefer_unit = error_unit
    q.dim = value_dim

    return q

def formula(quantity):
    """ returns error formula of quantity as latex code

    Args:
        quantity: Quantity object

    Returns:
        two HTML buttons showing actual formula and its latex code
    """

    assert isinstance(quantity, Quantity)

    if quantity.error_formula is None:
        raise ValueError("quantity '%s' doesn't have an error formula." % quantity.name)

    formula = quantity.error_formula

    # if formula is only a string
    if isinstance(formula,str):
        return formula
    # if formula is a sympy expression
    else:
        # replace "_err" by sigma function
        sigma = Function("\sigma")
        for var in formula.free_symbols:
            if var.name[-4:] == "_err":
                formula = formula.subs(var, sigma( Symbol(var.name[:-4], **var._assumptions)))
        # add equals sign
        latex_code = latex(sigma(quantity)) + " = " + latex(formula)

	# render two show/hide buttons
    form_button, form_code = pytex.hide_div('Formula', '$%s$' % (latex_code) , hide = False)
    latex_button, latex_code = pytex.hide_div('LaTex', latex_code)
    res = 'Error Formula for %s<div width=20px/>%s%s<hr/>%s<br>%s' % (
        '$%s$' % latex(quantity), form_button, latex_button, form_code, latex_code)

    return render_latex(res)

def table(*quants, maxcols=5, latex_only=False, table_only=False):
    """ shows quantities and their values in a table
    Args:
     - quants: quantities to be shown
     - maxcols: maximum number of columns
     - latex_only: if True, only returns latex code. If False, returns both latex
                   and actual table.
    """
    if latex_only:
        return qtable(*quants, html=False, maxcols=maxcols)[0]
    elif table_only:
        return qtable(*quants, html=False, maxcols=maxcols)[1]
    else:
        return render_latex(qtable(*quants, maxcols=maxcols))

def params(*names):
    """ creates empty quantities in order to be used as fit parameters
    Args:
     names: names of quantities to be created. Can be either one string using
            whitespaces as a separator or multiple strings.

    Returns:
    tuple of empty quantities
    """
    if len(names) == 1:
        names = names[0].split()
    return (Quantity(name) for name in names)


def fit(func, xdata, ydata, params, xvar=None, ydata_axes=None, weighted=None, absolute_sigma=False, ignore_dim=False):
    """ fits function to data and returns results in table and plot

    Args:
		func: sympy Expr of function to fit, e.g. n*t**2 + m*t + b
		xdata: sympy expression or list of sympy expressions of x-axis
			   data to fit to. xdata quantities must be 1-dimensional.
		ydata: sympy Expr of y-axis data to fit to
		params: list of parameters in fit function, e.g. [m, n, b]
        xvar: if specified, this is the quantity in fit function to be used as
              x-axis variable. Specify if xdata is not a quantity but an expression.
              Name or value of xvar don't matter.
        ydata_axes: int or tuple of ints. Specifies which axes of the ydata to use
        			for the fit. For other axes, fit will be repeated separately.
        yaxis_of_xdata: int or tuple of ints. Must have the same length as
        (only an idea)  xdata tuple. Specifies which axis in ydata belongs to each
                        xdata quantity. Default is (1,2,3,...).
		weighted: If True, will weight fit by errors (returns error if not possible).
				  If False, will not weight fit by errors.
				  If None, will try to weight fit, but if at least one error is
                  not given, will not weight it.
    	absolute_sigma: bool. If False, uses errors only to weight data points.
					    Overall magnitude of errors doesn't affect output errors.
					    If True, estimated output errors will be based on input
                        error magnitude.
		ignore_dim: if True, will ignore dimensions and just calculate in base units instead
    """

    # TODO: TESTING!!

	# make xdata and xvar a tuple if it's not already
    if not hasattr(xdata, '__iter__'):
        xdata = (xdata,)
    if xvar is not None:
        if not hasattr(xvar, '__iter__'):
            xvar = (xvar,)
        assert len(xvar)==len(xdata)
    else:
		# if xvar is not specified, use xdata as x-axis variable
        xvar = xdata

    for xaxis in range(len(xdata)):
		# if xdata is an expression, parse it
        if not isinstance(xdata[xaxis], Quantity):
            xdata[xaxis] = assign(xdata[xaxis])

		# then replace xvar by xdata, if necessary
        if not xvar[xaxis] is xdata[xaxis]:
            func = func.subs(xvar[xaxis], xdata[xaxis])

    # if ydata is an expression, parse it
    if not isinstance(ydata, Quantity):
        ydata = assign(ydata)

	# check if dimension is right
    if not ignore_dim:
        # find out function dimension
        try:
            func_dim = get_dimension(func)
        except (ValueError, RuntimeError):
            func_dim = None
        # if dimensions don't match
        if not func_dim == ydata.dim:
			# try to find right parameters dimensions
            known_dim = {}
            for q in func.free_symbols:
                if not q in params:
                    known_dim[q.name] = q.dim
            known_dim = dim_solve(func, ydata.dim, known_dim)
            # save dimensions to quantities
            for q in func.free_symbols:
                if not q.dim == known_dim[q.name]:
                    q.dim = known_dim[q.name]
                    q.prefer_unit = None
            func_dim = get_dimension(func)
			# if it still doesn't work, raise error
            if not func_dim == ydata.dim:
                raise RuntimeError("Finding dimensions of fit parameters was not successful.\n"\
									"Check fit function or specify parameter units manually.\n"\
									"This error will occur until dimensions are right.")

    # fit
    values, errors = fitting.fit(func, xdata, ydata, params, ydata_axes, weighted, absolute_sigma)

    # save results
    for i, p in enumerate(params):
        p.value = values[i]
        p.value_formula = "fit"
        p.error = errors[i]
        p.error_formula = "fit"

    # render two show/hide buttons
    form_button, form_code = pytex.hide_div('Results', table(*params, table_only=True), hide = False)
    latex_button, latex_code = pytex.hide_div('Plot', 'blub')
    res = 'Results of fit<div width=20px/>%s%s<hr/>%s<br>%s'\
            % (form_button, latex_button, form_code, latex_code)

    return render_latex(res)

def plot(*plots, xlabel=None, ylabel=None, xunit=None, yunit=None, xrange=None,
         yrange=None, legend=None, size=None, save_to=None, return_fig=False,
         ignore_dim=False, module="matplotlib"):
    """ Plots data or functions

    Args:
        plots: triplets of things to plot: x, y, options
               e.g. plot(t, h**2, {'color': 'r'},
                         t, 2*t*exp(t/t0), {'title':'theoretical curve'})

    new concept:
    plot(x1, y1, {color:"#fff", points:"o", ...}, x2, y2, {color:"r"}, xunit="m", yrange=[0,10], ...)

    data set properties:
        color, point style, line style/width, title, errorbars
    figure properties:
        legend, xunit, yunit, xrange, yrange, imagesize, save?/return_fig, ignore_dim
    """

    #TODO: Tests: dependency unpacking, ...

    # parse units
    if not xunit is None:
        xunit = parse_unit(xunit)[2]
    if not yunit is None:
        yunit = parse_unit(yunit)[2]

    # parse ranges
    if not xrange is None:
        xrange = [get_value(xrange[0]), get_value(xrange[1])]
    if not yrange is None:
        yrange = [get_value(yrange[0]), get_value(yrange[1])]

    x_dim = None
    y_dim = None

    # iterate all data/functions to plot
    i = 0
    data_sets = []
    functions = []
    while i+1<len(plots):

        # get x, y and options from plots array
        x = plots[i]
        y = plots[i+1]
        if i+2<len(plots) and (isinstance(plots[i+2], dict)
                            or isinstance(plots[i+2], str)):
            options = plots[i+2]
            i += 3
        else:
            options = {}
            i += 2

        if ignore_dim:
            xunit = S.One
            yunit = S.One

        if not ignore_dim:
            # check dimensions
            if x_dim is None:
                x_dim = get_dimension(x)
            else:
                if not x_dim == get_dimension(x):
                    raise RuntimeError("dimension mismatch\n%s != %s"
                                        % (x_dim, get_dimension(x)))
            if y_dim is None:
                y_dim = get_dimension(y)
            else:
                if not y_dim == get_dimension(y):
                    raise RuntimeError("dimension mismatch\n%s != %s"
                                        % (y_dim, get_dimension(y)))

        # find out if it's a function or data points
        if isinstance(x, Quantity):
            # if x is a single quantity ...
            unpacked_y = _find_all_dependencies(y, x)
            if unpacked_y.has(x):
                # ... and is part of the dependency of y,
                # then it must be a function

                # add label if not specified
                if not 'label' in options:
                    if isinstance(y, Quantity):
                        options['label'] = ((y.longname + " ") if y.longname else "") + str(y)
                    else:
                        options['label'] = str(unpacked_y)

                y = unpacked_y

                if not ignore_dim:
                    # get factors
                    x_factor, xunit = convert_to_unit(x_dim, output_unit=xunit)
                    y_factor, yunit = convert_to_unit(y_dim, output_unit=yunit)

                    # scale function to units
                    y = y.subs(x,x*x_factor) / y_factor

                functions.append((x, y, options))
                continue

        # otherwise, it's a data set

        # add label if not specified
        if not 'label' in options:
            if isinstance(y, Quantity):
                options['label'] = ((y.longname + " ") if y.longname else "") + str(y)
            else:
                options['label'] = str(y)

        # exchange expressions by dummy quantities
        if not isinstance(x, Quantity):
            x = assign(x)
        if not isinstance(y, Quantity):
            y = assign(y)

        if ignore_dim:
            xvalues = x.value
            xerrors = x.error
            yvalues = y.value
            yerrors = y.error
        else:
            # get values and errors all in one unit
            xvalues, xerrors, xunit = adjust_to_unit(x, unit = xunit)
            yvalues, yerrors, yunit = adjust_to_unit(y, unit = yunit)

        data_sets.append(((xvalues, xerrors), (yvalues, yerrors), options))

    if xlabel is None:
        xlabel = "" if xunit == S.One else "[" + str(xunit) + "]"
    if ylabel is None:
        ylabel = "" if yunit == S.One else "[" + str(yunit) + "]"

    # pass on to plotting module
    if module == 'matplotlib':
        out = matplot.plot(data_sets, functions, xlabel=xlabel, ylabel=ylabel,
                           xrange=xrange, yrange=yrange, legend=legend, size=size,
                           save_to=save_to)
        if return_fig:
            return out
    elif module == 'gnuplot':
        return gnuplot.plot(data_sets, functions, save=save_to, xrange=xrange,
                            yrange=yrange, x_label=xlabel, y_label=ylabel)
    else:
        raise ValueError("plotting module '%s' doesn't exist." % module)

def _find_all_dependencies(expr, find, ignore=[]):
    """
    unpacks quantities in <expr> until all dependencies from <find> are found
    """
    unpacked = expr
    for q in expr.free_symbols:
        if not q in ignore and isinstance(q.value_formula, Expr):
            ignore.append(q)
            content = _find_all_dependencies(q.value_formula, find=find, ignore=ignore)
            if find in content.free_symbols:
                unpacked = unpacked.subs(q, content)
    return unpacked
