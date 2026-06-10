async function test() {
  console.log("Starting fetch test to accounts.shopify.com...");
  try {
    const res = await fetch("https://destinations.shopifysvc.com/destinations/api/2020-07/graphql", {
      method: "GET"
    });
    console.log("Status:", res.status);
    const text = await res.text();
    console.log("Response text:", text.slice(0, 200));
  } catch (err) {
    console.error("Error occurred:", err);
  }
}

test();
