"""
statistics_distributions — ** Provide a reusable collection of statistical distributions with core properties and generation capabilities. Built for integration into scientific compute workflows, with a focus on flexibility and

### PART-META-JSON
{
  "name": "statistics_distributions",
  "layer": "scientific",
  "purpose": "Provide a reusable collection of statistical distributions with core properties and generation capabilities. Built for integration into scientific compute workflows, with a focus on flexibility and.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: NormalDistribution(...); PoissonDistribution(...); DistributionFactory(...) (plus more).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.scientific.statistics_distributions`.",
  "example": "from scrapyard.scientific.statistics_distributions import *",
  "import_path": "scrapyard.scientific.statistics_distributions"
}
### END-PART-META
"""
from scipy.stats import norm, poisson
import numpy as np
import sqlite3

class NormalDistribution:
    def __init__(self, mean: float = 0, std_dev: float = 1) -> None:
        if std_dev <= 0:
            raise ValueError("std_dev must be positive")
        self.mean = mean
        self.std_dev = std_dev

    def sample(self, size: int = 1) -> np.ndarray:
        return norm.rvs(loc=self.mean, scale=self.std_dev, size=size)

    def pdf(self, x: float) -> float:
        return norm.pdf(x, loc=self.mean, scale=self.std_dev)

    def cdf(self, x: float) -> float:
        return norm.cdf(x, loc=self.mean, scale=self.std_dev)


class PoissonDistribution:
    def __init__(self, lambda_rate: float = 1.0) -> None:
        if lambda_rate <= 0:
            raise ValueError("lambda_rate must be positive")
        self.lambda_rate = lambda_rate

    def sample(self, size: int = 1) -> np.ndarray:
        return poisson.rvs(mu=self.lambda_rate, size=size)

    def pmf(self, k: int) -> float:
        return poisson.pmf(k, mu=self.lambda_rate)

    def cdf(self, k: int) -> float:
        return poisson.cdf(k, mu=self.lambda_rate)


class DistributionFactory:
    @staticmethod
    def create(name: str, **params) -> 'Distribution':
        if name == 'NormalDistribution':
            return NormalDistribution(**params)
        elif name == 'PoissonDistribution':
            return PoissonDistribution(**params)
        else:
            raise ValueError(f"Unknown distribution type: {name}")


class Distribution:
    def __init__(self, **kwargs):
        self.parameters = dict(kwargs)

    def parameter(self, name: str):
        if name not in self.parameters:
            raise KeyError(name)
        return self.parameters[name]


def _selftest():
    # Create instances of known distributions
    normal_dist = NormalDistribution(mean=0, std_dev=1)
    poisson_dist = PoissonDistribution(lambda_rate=2.5)

    # Test sampling from distributions
    sample_size = 1000
    samples_normal = normal_dist.sample(sample_size)
    assert isinstance(samples_normal, np.ndarray) and samples_normal.shape == (sample_size,), "Normal distribution sampling failed"
    
    samples_poisson = poisson_dist.sample(sample_size)
    assert isinstance(samples_poisson, np.ndarray) and samples_poisson.shape == (sample_size,), "Poisson distribution sampling failed"

    # Test PDF/PMF/CDF values
    x_val = 0.5
    k_val = 2

    pdf_normal = normal_dist.pdf(x_val)
    assert isinstance(pdf_normal, float), "Normal distribution PDF returned non-float value"
    
    pmf_poisson = poisson_dist.pmf(k_val)
    assert isinstance(pmf_poisson, float), "Poisson distribution PMF returned non-float value"
    
    cdf_normal = normal_dist.cdf(x_val)
    assert isinstance(cdf_normal, float) and 0 <= cdf_normal <= 1, "Normal distribution CDF returned out of range value"

    cdf_poisson = poisson_dist.cdf(k_val)
    assert isinstance(cdf_poisson, float) and 0 <= cdf_poisson <= 1, "Poisson distribution CDF returned out of range value"

    # Test factory creation
    normal_from_factory = DistributionFactory.create('NormalDistribution', mean=0, std_dev=1)
    poisson_from_factory = DistributionFactory.create('PoissonDistribution', lambda_rate=2.5)

    assert isinstance(normal_from_factory, NormalDistribution) and \
           isinstance(poisson_from_factory, PoissonDistribution), "Factory creation failed"
    generic = Distribution(scale=2.0)
    assert generic.parameter("scale") == 2.0
    try:
        generic.parameter("missing")
        raise AssertionError("missing parameter did not raise")
    except KeyError:
        pass

    # Close all SQLite connections (if any were opened for self-test)
    conn = sqlite3.connect(":memory:")
    conn.close()

    print("Self-test passed successfully!")


if __name__ == "__main__":
    _selftest()
