from __future__ import absolute_import, division, print_function

from abc import ABCMeta, abstractmethod

from six import add_metaclass

import pyro
import pyro.distributions as dist


@add_metaclass(ABCMeta)
class Feature(object):
    """
    A hierarchical mixture model for a single observed feature type.

    Feature models are intended as an adapter between latent categorical
    variables and observed variables of various other datatypes.  Feature
    models are agnostic to component weight models, which may e.g. be driven
    by a neural network. Thus users must sample component membership from a
    user-provided distribution.

    Example usage::

        # User must provide a membership distribution.
        num_components = 10
        weights = pyro.param("component_weights",
                             torch.ones(num_components) / num_components,
                             constraint=constraints.simplex)
        membership_dist = dist.Categorical(weights)

        # Feature objects adapt the component id to a given feature type.
        f = MyFeature("foo")
        shared = f.sample_shared()
        with pyro.plate("components", num_components):
            group = f.sample_group(shared)  # broadcasts to each component
        with pyro.plate("data", len(data)):
            component = pyro.sample("component", membership_dist)
            pyro.sample("obs", f.value_dist(group, component), obs=data)

    :param str name: The name of this feature, used as a prefix for
        :func:`pyro.sample` statements inside :meth:`sample_shared` and
        :meth:`sample_group`.
    """
    def __init__(self, name):
        self.name = name

    def __str__(self):
        return '{}("{}")'.format(type(self).__name__, self.name)

    @abstractmethod
    def sample_shared(self):
        """
        Samples parameters of this feature model that are shared by all mixture
        components.

        :returns: an opaque result to be passed to :meth:`sample_group`.
        """
        raise NotImplementedError

    @abstractmethod
    def sample_group(self, shared):
        """
        Samples per-component parameters of this feature model. This should be
        called inside a vectorized :class:`~pyro.plate` over the desired
        number of components. This is intended to be executed inside an
        :class:`~pyro.plate` over the number of components.

        :returns: an opaque result to be passed to :meth:`value_dist`.
        """
        raise NotImplementedError

    @abstractmethod
    def value_dist(self, group, component):
        """
        Constructs a :class:`~pyro.distributions.TorchDistribution`
        object conditioned on the given component index.

        :param group: an opaque result of :meth:`sample_group`
        :param torch.LongTensor component: a component id or batch of component
            ids
        :returns: a component distribution object
        :rtype: pyro.distributions.TorchDistribution
        """
        raise NotImplementedError


class Boolean(Feature):
    def sample_shared(self):
        alpha = pyro.sample("{}_alpha".format(self.name), dist.Gamma(0.5, 1.))
        beta = pyro.sample("{}_beta".format(self.name), dist.Gamma(0.5, 1.))
        return alpha, beta

    def sample_group(self, shared):
        alpha, beta = shared
        probs = pyro.sample("{}_probs".format(self.name), dist.Beta(alpha, beta))
        return probs

    def value_dist(self, group, component):
        probs = group
        return dist.Bernoulli(probs[component])


class Real(Feature):
    def sample_shared(self):
        loc_loc = pyro.sample("{}_loc_loc".format(self.name), dist.Normal(0., 1.))
        hyper_scale = pyro.sample("{}_hyper_scale".format(self.name), dist.LogNormal(0., 10.))
        scale_alpha = pyro.sample("{}_scale_alpha".format(self.name), dist.Gamma(0.5, 1.))
        scale_beta = pyro.sample("{}_scale_beta".format(self.name), dist.Gamma(0.5, 1.))
        return loc_loc, hyper_scale, scale_alpha, scale_beta

    def sample_group(self, shared):
        loc_loc, hyper_scale, scale_alpha, scale_beta = shared
        scale = pyro.sample("{}_scale".format(self.name),
                            dist.Gamma(scale_alpha, scale_beta)).pow(-0.5)
        loc = pyro.sample("{}_loc".format(self.name),
                          dist.Normal(loc_loc * scale, scale))
        return loc, scale

    def value_dist(self, group, component):
        loc, scale = group
        return dist.Normal(loc[component], scale[component])
