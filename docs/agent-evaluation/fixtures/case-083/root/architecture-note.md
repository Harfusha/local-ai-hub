# Workload isolation decision

Interactive requests and background export batches run in separate processing lanes. Interactive requests need predictable response times, so a long export cannot occupy their execution capacity. Batch exports instead maximize throughput and can pause or resume without changing the response-time target. The separation also lets operators apply different concurrency limits and inspect each workload independently.

This synthetic architecture note deliberately uses alternate terminology for the processing lanes.
