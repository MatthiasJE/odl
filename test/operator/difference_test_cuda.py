# Copyright 2014, 2015 The ODL development group
#
# This file is part of ODL.
#
# ODL is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# ODL is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with ODL.  If not, see <http://www.gnu.org/licenses/>.


# Imports for common Python 2/3 codebase
from __future__ import division, print_function, unicode_literals
from __future__ import absolute_import
from future import standard_library

# External module imports
import unittest

# ODL imports
from odl.discr.discretization import uniform_discretization
from odl.operator.operator import LinearOperator
from odl.space.function import L2
from odl.space.set import Interval, Rectangle
from odl.space.product import productspace

from odl.utility.testutils import skip_all_tests

try:
    from odl.space.cuda import CudaRn
    import odlpp.odlpp_cuda as cuda
    from odl.utility.testutils import ODLTestCase
except ImportError:
    ODLTestCase = skip_all_tests("Missing odlpp")

standard_library.install_aliases()


class ForwardDiff(LinearOperator):
    """ Calculates the circular convolution of two CUDA vectors
    """

    def __init__(self, space):
        if not isinstance(space, CudaRn):
            raise TypeError("space must be CudaRn")

        self.domain = self.range = space

    def _apply(self, rhs, out):
        cuda.forward_diff(rhs.data, out.data)

    @property
    def adjoint(self):
        return ForwardDiffAdjoint(self.domain)


class ForwardDiffAdjoint(LinearOperator):
    """ Calculates the circular convolution of two CUDA vectors
    """

    def __init__(self, space):
        if not isinstance(space, CudaRn):
            raise TypeError("space must be CudaRn")

        self.domain = self.range = space

    def _apply(self, rhs, out):
        cuda.forward_diff_adj(rhs.data, out.data)

    @property
    def adjoint(self):
        return ForwardDiff(self.domain)


class ForwardDiff2D(LinearOperator):
    """ Calculates the circular convolution of two CUDA vectors
    """

    def __init__(self, space):
        if not isinstance(space, CudaRn):
            raise TypeError("space must be CudaPixelDiscretization")

        self.domain = space
        self.range = productspace(space, space)

    def _apply(self, rhs, out):
        cuda.forward_diff_2d(rhs.data, out[0].data, out[1].data,
                             self.domain.shape[0], self.domain.shape[1])

    @property
    def adjoint(self):
        return ForwardDiff2DAdjoint(self.domain)


class ForwardDiff2DAdjoint(LinearOperator):
    """ Calculates the circular convolution of two CUDA vectors
    """

    def __init__(self, space):
        if not isinstance(space, CudaRn):
            raise TypeError("space must be CudaPixelDiscretization")

        self.domain = productspace(space, space)
        self.range = space

    def _apply(self, rhs, out):
        cuda.forward_diff_2d_adj(rhs[0].data, rhs[1].data, out.data,
                                 self.range.shape[0], self.range.shape[1])

    @property
    def adjoint(self):
        return ForwardDiff2D(self.range)


class TestCudaForwardDifference(ODLTestCase):
    def test_fwd_diff(self):
        # Continuous definition of problem
        I = Interval(0, 1)
        space = L2(I)

        # Discretization
        n = 6
        rn = CudaRn(n)
        d = uniform_discretization(space, rn)
        fun = d.element([1, 2, 5, 3, 2, 1])

        # Create operator
        diff = ForwardDiff(d)

        self.assertAllAlmostEquals(diff(fun), [0, 3, -2, -1, -1, 0])
        self.assertAllAlmostEquals(diff.T(fun), [0, -1, -3, 2, 1, 0])
        self.assertAllAlmostEquals(diff.T(diff(fun)), [0, -3, 5, -1, 0, 0])


class TestCudaForwardDifference2D(ODLTestCase):
    def test_square(self):
        # Continuous definition of problem
        I = Rectangle([0, 0], [1, 1])
        space = L2(I)

        # Discretization
        n = 5
        m = 5
        rn = CudaRn(n*m)
        d = uniform_discretization(space, rn, (n, m))
        x, y = d.points()
        fun = d.element([[0, 0, 0, 0, 0],
                         [0, 0, 0, 0, 0],
                         [0, 0, 1, 0, 0],
                         [0, 0, 0, 0, 0],
                         [0, 0, 0, 0, 0]])

        diff = ForwardDiff2D(d)
        derivative = diff(fun)
        self.assertAllAlmostEquals(derivative[0][:].reshape(n, m),
                                   [[0, 0, 0, 0, 0],
                                    [0, 0, 0, 0, 0],
                                    [0, 1, -1, 0, 0],
                                    [0, 0, 0, 0, 0],
                                    [0, 0, 0, 0, 0]])

        self.assertAllAlmostEquals(derivative[1][:].reshape(n, m),
                                   [[0, 0, 0, 0, 0],
                                    [0, 0, 1, 0, 0],
                                    [0, 0, -1, 0, 0],
                                    [0, 0, 0, 0, 0],
                                    [0, 0, 0, 0, 0]])

        # Verify that the adjoint is ok
        # -gradient.T(gradient(x)) is the laplacian
        laplacian = -diff.T(derivative)
        self.assertAllAlmostEquals(laplacian[:].reshape(n, m),
                                   [[0, 0, 0, 0, 0],
                                    [0, 0, 1, 0, 0],
                                    [0, 1, -4, 1, 0],
                                    [0, 0, 1, 0, 0],
                                    [0, 0, 0, 0, 0]])

    def test_rectangle(self):
        # Continuous definition of problem
        I = Rectangle([0, 0], [1, 1])
        space = L2(I)

        # Complicated functions to check performance
        n = 5
        m = 7

        # Discretization
        rn = CudaRn(n*m)
        d = uniform_discretization(space, rn, (n, m))
        x, y = d.points()
        fun = d.element([[0, 0, 0, 0, 0, 0, 0],
                         [0, 0, 0, 0, 0, 0, 0],
                         [0, 0, 1, 0, 0, 0, 0],
                         [0, 0, 0, 0, 0, 0, 0],
                         [0, 0, 0, 0, 0, 0, 0]])

        diff = ForwardDiff2D(d)
        derivative = diff(fun)

        self.assertAllAlmostEquals(derivative[0][:].reshape(n, m),
                                   [[0, 0, 0, 0, 0, 0, 0],
                                    [0, 0, 0, 0, 0, 0, 0],
                                    [0, 1, -1, 0, 0, 0, 0],
                                    [0, 0, 0, 0, 0, 0, 0],
                                    [0, 0, 0, 0, 0, 0, 0]])

        self.assertAllAlmostEquals(derivative[1][:].reshape(n, m),
                                   [[0, 0, 0, 0, 0, 0, 0],
                                    [0, 0, 1, 0, 0, 0, 0],
                                    [0, 0, -1, 0, 0, 0, 0],
                                    [0, 0, 0, 0, 0, 0, 0],
                                    [0, 0, 0, 0, 0, 0, 0]])

        # Verify that the adjoint is ok
        # -gradient.T(gradient(x)) is the laplacian
        laplacian = -diff.T(derivative)
        self.assertAllAlmostEquals(laplacian[:].reshape(n, m),
                                   [[0, 0, 0, 0, 0, 0, 0],
                                    [0, 0, 1, 0, 0, 0, 0],
                                    [0, 1, -4, 1, 0, 0, 0],
                                    [0, 0, 1, 0, 0, 0, 0],
                                    [0, 0, 0, 0, 0, 0, 0]])


if __name__ == '__main__':
    unittest.main(exit=False)