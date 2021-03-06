#!/usr/bin/env python3

import torch
from .kernel import Kernel
from ..lazy import delazify
from ..constraints import Positive


class ScaleKernel(Kernel):
    r"""
    Decorates an existing kernel object with an output scale, i.e.

    .. math::

       \begin{equation*}
          K_{\text{scaled}} = \theta_\text{scale} K_{\text{orig}}
       \end{equation*}

    where :math:`\theta_\text{scale}` is the `outputscale` parameter.

    In batch-mode (i.e. when :math:`x_1` and :math:`x_2` are batches of input matrices), each
    batch of data can have its own `outputscale` parameter by setting the `batch_shape`
    keyword argument to the appropriate number of batches.

    .. note::
        The :attr:`outputscale` parameter is parameterized on a log scale to constrain it to be positive.
        You can set a prior on this parameter using the :attr:`outputscale_prior` argument.

    Args:
        :attr:`base_kernel` (Kernel):
            The base kernel to be scaled.
        :attr:`batch_shape` (int, optional):
            Set this if you want a separate outputscale for each batch of input data. It should be `b`
            if :attr:`x1` is a `b x n x d` tensor. Default: `torch.Size([])`
        :attr:`outputscale_prior` (Prior, optional): Set this if you want to apply a prior to the outputscale
            parameter.  Default: `None`
        :attr:`outputscale_constraint` (Constraint, optional): Set this if you want to apply a constraint to the
            outputscale parameter. Default: `Positive`.

    Attributes:
        :attr:`base_kernel` (Kernel):
            The kernel module to be scaled.
        :attr:`outputscale` (Tensor):
            The outputscale parameter. Size/shape of parameter depends on the :attr:`batch_shape` arguments.

    Example:
        >>> x = torch.randn(10, 5)
        >>> base_covar_module = gpytorch.kernels.RBFKernel()
        >>> scaled_covar_module = gpytorch.kernels.ScaleKernel(base_covar_module)
        >>> covar = scaled_covar_module(x)  # Output: LazyTensor of size (10 x 10)
    """

    def __init__(self, base_kernel, outputscale_prior=None, outputscale_constraint=None, **kwargs):
        super(ScaleKernel, self).__init__(has_lengthscale=False, **kwargs)
        if outputscale_constraint is None:
            outputscale_constraint = Positive()

        self.base_kernel = base_kernel
        outputscale = torch.zeros(*self.batch_shape) if len(self.batch_shape) else torch.tensor(0.)
        self.register_parameter(name="raw_outputscale", parameter=torch.nn.Parameter(outputscale))
        if outputscale_prior is not None:
            self.register_prior(
                "outputscale_prior", outputscale_prior, lambda: self.outputscale, lambda v: self._set_outputscale(v)
            )

        self.register_constraint("raw_outputscale", outputscale_constraint)

    @property
    def outputscale(self):
        return self.raw_outputscale_constraint.transform(self.raw_outputscale)

    @outputscale.setter
    def outputscale(self, value):
        self._set_outputscale(value)

    def _set_outputscale(self, value):
        if not torch.is_tensor(value):
            value = torch.as_tensor(value).to(self.raw_outputscale)
        self.initialize(raw_outputscale=self.raw_outputscale_constraint.inverse_transform(value))

    def forward(self, x1, x2, batch_dims=None, diag=False, **params):
        outputscales = self.outputscale
        if batch_dims == (0, 2):
            outputscales = outputscales.unsqueeze(0).repeat(x1.size(-1), *([1] * outputscales.dim()))

        orig_output = self.base_kernel.forward(x1, x2, diag=diag, batch_dims=batch_dims, **params)
        outputscales = outputscales.view(*outputscales.shape, *([1] * (orig_output.dim() - outputscales.dim())))

        if diag:
            return delazify(orig_output) * outputscales
        return orig_output.mul(outputscales)

    def size(self, x1, x2):
        return self.base_kernel.size(x1, x2)
