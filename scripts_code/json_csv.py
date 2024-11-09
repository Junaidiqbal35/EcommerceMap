# import pandas as pd
#
# # Load the JSON file
# json_file_path = "LayerList.json"
# csv_file_path = "LayerList.csv"
#
# # Read the JSON file into a DataFrame
# df = pd.read_json(json_file_path)
#
# # Save the DataFrame as a CSV file
# df.to_csv(csv_file_path, index=False)
#
# print(f"Successfully converted {json_file_path} to {csv_file_path}")
import pandas as pd
import json

# File paths
csv_file_path = "Layer-2024-10-09.csv"
json_file_path = "LayerList.json"
output_csv_path = "Layer-2024-10-09.csv"

# Step 1: Read the CSV file
csv_df = pd.read_csv(csv_file_path)

# Step 2: Read the JSON file
with open(json_file_path, 'r') as json_file:
    json_data = json.load(json_file)

# Convert the 'layers' list to a DataFrame
json_df = pd.DataFrame(json_data['layers'])

# Step 3: Merge DataFrames based on 'layer_id'
# Use a left join to retain all rows from the CSV, and bring in `type` values from JSON
merged_df = csv_df.merge(json_df[['layer_id', 'type']], on='layer_id', how='left')

# Step 4: Update the CSV 'type' column with the values from the JSON DataFrame
# Use the `type_y` column (from JSON) to fill missing `type` values in the CSV
merged_df['type'] = merged_df['type_x'].combine_first(merged_df['type_y'])

# Drop the helper columns `type_x` and `type_y`
merged_df = merged_df.drop(columns=['type_x', 'type_y'])

# Step 5: Save the updated DataFrame back to a CSV file
merged_df.to_csv(output_csv_path, index=False)

print(f"CSV file has been successfully updated and saved as {output_csv_path}.")
