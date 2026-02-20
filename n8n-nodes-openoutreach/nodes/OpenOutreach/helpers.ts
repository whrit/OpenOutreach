import { IDataObject, IExecuteFunctions, ILoadOptionsFunctions, sleep } from 'n8n-workflow';

/**
 * Make an authenticated request to the OpenOutreach REST API.
 *
 * Uses this.helpers.httpRequest() — the current n8n-workflow API (not the
 * deprecated this.helpers.request()). Credentials are read from the
 * 'openOutreachApi' credential vault (baseUrl + apiKey fields).
 *
 * @param method   HTTP method
 * @param path     API path beginning with '/' (e.g. '/jobs/42/')
 * @param body     Optional JSON request body
 * @param qs       Optional query-string parameters
 */
export async function openOutreachRequest(
	this: IExecuteFunctions | ILoadOptionsFunctions,
	method: 'GET' | 'POST' | 'PATCH' | 'DELETE',
	path: string,
	body?: IDataObject,
	qs?: IDataObject,
): Promise<IDataObject | IDataObject[]> {
	const credentials = await this.getCredentials('openOutreachApi');
	const baseUrl = (credentials.baseUrl as string).replace(/\/$/, '');
	const apiKey = credentials.apiKey as string;

	const options = {
		method,
		url: `${baseUrl}/api/v1${path}`,
		headers: {
			Authorization: `Api-Key ${apiKey}`,
			'Content-Type': 'application/json',
		} as IDataObject,
		body,
		qs,
		json: true,
	};

	return this.helpers.httpRequest(options);
}

/**
 * Poll GET /jobs/{jobId}/ every intervalMs until status is 'completed' or
 * 'failed', or until timeoutMs elapses.
 *
 * @param ctx        IExecuteFunctions context (provides credentials + helpers)
 * @param jobId      The job_id string returned by the lane trigger endpoint
 * @param timeoutMs  Maximum wait time in milliseconds (default: 300 000 = 5 min)
 * @param intervalMs Poll interval in milliseconds (default: 5 000 = 5 s)
 * @returns          The final job object (status 'completed' or 'failed')
 */
export async function pollJobUntilDone(
	ctx: IExecuteFunctions,
	jobId: string,
	timeoutMs = 300_000,
	intervalMs = 5_000,
): Promise<IDataObject> {
	const deadline = Date.now() + timeoutMs;

	while (Date.now() < deadline) {
		const job = (await openOutreachRequest.call(ctx, 'GET', `/jobs/${jobId}/`)) as IDataObject;
		const status = job.status as string;

		if (status === 'completed' || status === 'failed') {
			return job;
		}

		await sleep(intervalMs);
	}

	throw new Error(`Job ${jobId} timed out after ${timeoutMs / 1000}s`);
}
