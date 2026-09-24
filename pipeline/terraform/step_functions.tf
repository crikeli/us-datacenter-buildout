resource "aws_sfn_state_machine" "pipeline" {
  name     = "${var.project_name}-pipeline"
  role_arn = aws_iam_role.step_functions.arn

  definition = jsonencode({
    Comment = "Clean the real FracTracker export with Glue, then crawl the result into the Glue Data Catalog for Redshift Spectrum / COPY."
    StartAt = "CleanFacilities"
    States = {
      CleanFacilities = {
        Type     = "Task"
        Resource = "arn:aws:states:::glue:startJobRun.sync"
        Parameters = {
          JobName = aws_glue_job.clean_facilities.name
        }
        Next = "CrawlCleanData"
      }
      CrawlCleanData = {
        Type     = "Task"
        Resource = "arn:aws:states:::aws-sdk:glue:startCrawler"
        Parameters = {
          Name = aws_glue_crawler.facilities_clean.name
        }
        End = true
      }
    }
  })
}
