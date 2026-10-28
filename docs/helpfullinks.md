# Helpful Links & References Index

*Efficient Re-Evaluation of Pending Workloads in Carbon-Aware Datacentre Scheduling*  
*Compiled 24 Oct 2026; Indian sources added 29 Oct 2026 (PRD v0.5).*

`[checked]` = opened or downloaded during the PRD audit.  
`[from report]` = carried over from the EL report.

---

## 1. Workload Data (Alibaba GPU Trace v2020, MVP Dataset)

- **Repository and Trace Releases `[checked]`**
  - [Alibaba ClusterData Repository](https://github.com/alibaba/clusterdata)
- **v2020 Schema, Checksums & Downloads `[checked]`**
  - [cluster-trace-gpu-v2020 Documentation](https://github.com/alibaba/clusterdata/tree/master/cluster-trace-gpu-v2020)
- **Direct Downloads (Alibaba OSS)** *(MVP needs only the first three)*
  - [`pai_job_table.tar.gz` (60 MB)](https://aliopentrace.oss-cn-beijing.aliyuncs.com/v2020GPUTraces/pai_job_table.tar.gz)
  - [`pai_task_table.tar.gz` (34 MB)](https://aliopentrace.oss-cn-beijing.aliyuncs.com/v2020GPUTraces/pai_task_table.tar.gz)
  - [`pai_machine_spec.tar.gz` (32 KB)](https://aliopentrace.oss-cn-beijing.aliyuncs.com/v2020GPUTraces/pai_machine_spec.tar.gz)
- **GitHub Mirror (Split Parts) `[checked]`**
  - [qzweng/clusterdata-cluster-trace-gpu-v2020-data](https://github.com/qzweng/clusterdata-cluster-trace-gpu-v2020-data)
- **Primary Trace Citation `[checked]`**
  - Q. Weng et al., *"MLaaS in the Wild: Workload Analysis and Scheduling in Large-Scale Heterogeneous GPU Clusters,"* USENIX NSDI '22. [USENIX Paper](https://www.usenix.org/conference/nsdi22/presentation/weng)

---

## 2. Indian Grid Data (simulated world)

- **Central Electricity Authority: CO2 Baseline Database for the Indian Power Sector** *(emission factors; also the likely "established table" the principal meant)*
  - [CEA website](https://cea.nic.in/)
  - [User Guide v21.0 (PDF)](https://cea.nic.in/wp-content/uploads/baseline/2025/12/User_Guide_V_21.0.pdf)
- **Grid-India (NLDC/RLDC) reports** *(preferred source for regional generation by fuel; blocker B4)*
  - [Grid-India](https://grid-india.in/)
- **Candidate secondary sources** *(licences unchecked)*
  - [Energymap data shop: hourly state-level carbon intensity](https://www.energymap.in/data-shop)
  - [Grid-India hourly demand, solar and wind, Sep 2021 – Jun 2025 (Mendeley)](https://data.mendeley.com/datasets/y58jknpgs8)
  - [NLDC daily power supply position reports (Kaggle)](https://www.kaggle.com/datasets/halcyonvector/india-power-grid-nldc-daily-psp-reports)
  - [Ember India electricity data (monthly; cross-checks only)](https://ember-energy.org/data/india-electricity-data/)

---

## 2b. Forecast-Error Source (NESO archive, Great Britain)

*Used only for the shape of real forecast errors, applied to Indian truth (PRD §6.2.4).*

- **Forecast-Vintage Archive `[checked]`**
  - [nmpowell/carbon-intensity-forecast-tracking Repository](https://github.com/nmpowell/carbon-intensity-forecast-tracking)
- **Official Carbon Intensity API `[checked]`**
  - [API Documentation](https://api.carbonintensity.org.uk/)
  - [API Definitions](https://carbon-intensity.github.io/api-definitions/)
- **NESO Data Portal Datasets `[from report]`**
  - [Regional Carbon Intensity Forecast](https://www.neso.energy/data-portal/regional-carbon-intensity-forecast)
  - [NESO Data Portal Home](https://www.neso.energy/data-portal)

---

## 3. Emissions Reference Candidates

- **CEA CO2 Baseline Database** (see Section 2): the working answer since PRD v0.5
- **UK Government GHG Conversion Factors 2026 (DESNZ) `[checked]`** *(superseded by CEA for the Indian setting)*
  - [GHG Reporting Conversion Factors 2026](https://www.gov.uk/government/publications/greenhouse-gas-reporting-conversion-factors-2026)
- **Accounting Boundary Context `[from report]`**
  - [GHG Protocol Scope 2 Guidance](https://ghgprotocol.org/scope-2-guidance)

---

## 4. Scheduling Theory

- **M. L. Pinedo, *Scheduling: Theory, Algorithms, and Systems*, 6th ed., Springer, 2022 `[checked]`**
  - [Springer Link (DOI)](https://doi.org/10.1007/978-3-031-05921-6)

---

## 5. Related Literature & Prior Work

- A. Radovanović et al., *"Carbon-Aware Computing for Datacenters,"* IEEE TPWRS 2023. [DOI](https://doi.org/10.1109/TPWRS.2022.3173250)
- S. Hall et al., *"Carbon-Aware Computing for Data Centers with Probabilistic Performance Guarantees,"* IEEE TPWRS 2025. [DOI](https://doi.org/10.1109/TPWRS.2025.3630499)
- A. Li, S. Liu, Y. Ding, *"Uncertainty-Aware Decarbonization for Datacenters,"* HotCarbon '24. [PDF](https://hotcarbon.org/assets/2024/pdf/hotcarbon24-final84.pdf)
- T. Sukprasert et al., *"On the Limitations of Carbon-Aware Temporal and Spatial Workload Shifting in the Cloud,"* EuroSys '24. [DOI](https://doi.org/10.1145/3627703.3650079)
- W. A. Hanafy et al., *"Untangling the Carbon-Cost Tradeoffs and Stampede Effect Challenges in Cloud Computing,"* IEEE TC 2026. [DOI](https://doi.org/10.1109/TC.2026.3667610)
- W. A. Hanafy et al., *"CarbonScaler: Carbon-Aware Execution for Elastic Cloud Workloads,"* SIGMETRICS 2024. *(Source for `pred_error(ε)`)*
- K. Xu et al., *"GREEN: Carbon-efficient Resource Scheduling for Machine Learning Clusters,"* USENIX NSDI 2025. *(Source for `periodic(T)`)*

---

## 6. Development Tools & Libraries

- [uv - Python Packaging](https://docs.astral.sh/uv/)
- [pandas Documentation](https://pandas.pydata.org/docs/)
- [NumPy Documentation](https://numpy.org/doc/stable/)
- [heapq Standard Library](https://docs.python.org/3.12/library/heapq.html)
- [PyYAML Documentation](https://pyyaml.org/wiki/PyYAMLDocumentation)
- [Matplotlib Documentation](https://matplotlib.org/stable/)
- [pytest Documentation](https://docs.pytest.org/)
- [Ruff Linter & Formatter](https://docs.astral.sh/ruff/)

---

## 7. Strategic Context

- [UN Sustainable Development Goal 9](https://sdgs.un.org/goals/goal9)
