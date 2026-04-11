from pdf2image import convert_from_path

pdf_path = r"C:\LSC\contract_sorter\input\test.pdf"
poppler_path = r"C:\poppler-25.12.0\Library\bin"

images = convert_from_path(
    pdf_path,
    first_page=1,
    last_page=1,
    poppler_path=poppler_path
)

print(f"Converted pages: {len(images)}")
print(f"First image size: {images[0].size}")